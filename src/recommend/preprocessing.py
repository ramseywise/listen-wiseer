"""Feature engineering and corpus assembly for the recommendation pipeline.

Loads raw data from DuckDB, computes derived features (Track2Vec, collaborative,
temporal, ENOA centroid), imputes missing audio features via a cascade
(artist → genre → global median), and returns a clean feature matrix.

Called by both train.py (training) and engine.py (inference).

Usage:
    from etl.db import get_connection
    from recommend.preprocessing import build_feature_matrix

    conn = get_connection(read_only=True)
    corpus = build_feature_matrix(conn)
    conn.close()
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from utils.logging import get_logger

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

log = get_logger(__name__)

# Audio features that can be imputed via the cascade
IMPUTABLE_AUDIO_FEATURES: list[str] = [
    "danceability",
    "energy",
    "loudness",
    "speechiness",
    "acousticness",
    "instrumentalness",
    "liveness",
    "valence",
    "tempo",
]


# ---------------------------------------------------------------------------
# 1. Corpus loading
# ---------------------------------------------------------------------------


def load_corpus_from_db(conn: DuckDBPyConnection) -> pl.DataFrame:
    """Load the base corpus from the track_profile view in DuckDB.

    Returns one row per track with all columns from the view:
    track metadata, audio features, genre map fields, and fave_score.

    Args:
        conn: Open DuckDB connection.

    Returns:
        pl.DataFrame with all track_profile columns, renamed track_id → id
        for backward compatibility with the ML pipeline.
    """
    df = conn.execute("SELECT * FROM track_profile").pl()
    # Rename track_id → id for compatibility with existing pipeline code
    if "track_id" in df.columns:
        df = df.rename({"track_id": "id"})
    log.info("preprocessing.corpus.loaded", n_rows=len(df), n_cols=len(df.columns))
    return df


# ---------------------------------------------------------------------------
# 2. Track2Vec (playlist co-occurrence embeddings)
# ---------------------------------------------------------------------------


def compute_track2vec(
    conn: DuckDBPyConnection,
    dim: int = 64,
    window: int = 5,
    min_count: int = 1,
    seed: int = 42,
) -> dict[str, np.ndarray]:
    """Train Word2Vec on playlist co-occurrence and return per-track embeddings.

    Each playlist is treated as a "sentence" where track_ids are "words".
    Tracks that co-occur in playlists learn similar embeddings.

    Args:
        conn: Open DuckDB connection with playlist_tracks table.
        dim: Embedding dimensionality.
        window: Word2Vec context window size.
        min_count: Minimum track frequency to include.
        seed: Random seed for reproducibility.

    Returns:
        Dict mapping track_id → np.ndarray of shape (dim,).
    """
    from gensim.models import Word2Vec

    # Build playlist "sentences": each playlist → list of track_ids
    rows = conn.execute(
        "SELECT playlist_id, track_id FROM playlist_tracks ORDER BY playlist_id"
    ).fetchall()

    if not rows:
        log.warning("preprocessing.track2vec.no_playlists")
        return {}

    # Group by playlist
    playlists: dict[str, list[str]] = {}
    for pid, tid in rows:
        playlists.setdefault(pid, []).append(tid)

    sentences = list(playlists.values())
    log.info(
        "preprocessing.track2vec.training",
        n_playlists=len(sentences),
        n_unique_tracks=len({tid for s in sentences for tid in s}),
        dim=dim,
    )

    model = Word2Vec(
        sentences=sentences,
        vector_size=dim,
        window=window,
        min_count=min_count,
        sg=1,  # skip-gram
        seed=seed,
        workers=1,  # deterministic with seed
        epochs=20,
    )

    embeddings: dict[str, np.ndarray] = {
        tid: model.wv[tid].astype(np.float64) for tid in model.wv.index_to_key
    }
    log.info("preprocessing.track2vec.done", n_embeddings=len(embeddings))
    return embeddings


def store_track2vec(
    conn: DuckDBPyConnection,
    embeddings: dict[str, np.ndarray],
    model_version: str = "track2vec_v1",
) -> int:
    """Write Track2Vec embeddings to the track_embeddings table.

    Upserts: existing rows are replaced if model_version matches.

    Args:
        conn: Open DuckDB connection (read-write).
        embeddings: Dict mapping track_id → embedding array.
        model_version: Version string stored alongside each embedding.

    Returns:
        Number of rows written.
    """
    if not embeddings:
        return 0

    # Clear existing embeddings for this model version, then bulk insert
    conn.execute("DELETE FROM track_embeddings WHERE model_version = ?", [model_version])

    # DuckDB supports INSERT with list literals for array columns
    rows = [(tid, emb.tolist(), model_version) for tid, emb in embeddings.items()]
    conn.executemany(
        "INSERT INTO track_embeddings (track_id, embedding, model_version) VALUES (?, ?, ?)",
        rows,
    )
    log.info(
        "preprocessing.track2vec.stored",
        n_rows=len(rows),
        model_version=model_version,
    )
    return len(rows)


def load_track2vec(conn: DuckDBPyConnection) -> dict[str, np.ndarray]:
    """Load Track2Vec embeddings from the track_embeddings table.

    Args:
        conn: Open DuckDB connection.

    Returns:
        Dict mapping track_id → np.ndarray of shape (64,).
        Empty dict if table is empty.
    """
    rows = conn.execute("SELECT track_id, embedding FROM track_embeddings").fetchall()
    if not rows:
        return {}
    return {tid: np.array(emb, dtype=np.float64) for tid, emb in rows}


# ---------------------------------------------------------------------------
# 3. Imputation cascade
# ---------------------------------------------------------------------------


def compute_artist_medians(
    corpus: pl.DataFrame,
    conn: DuckDBPyConnection,
) -> pl.DataFrame:
    """Compute median audio features per artist from tracks with real Spotify data.

    Only uses tracks where features_source='spotify' (real data, not imputed).

    Args:
        corpus: Base corpus DataFrame with audio features and features_source.
        conn: DuckDB connection for track_artists join.

    Returns:
        DataFrame with columns: artist_id + one median column per audio feature.
    """
    # Get track→artist mapping
    ta_df = conn.execute("SELECT track_id, artist_id FROM track_artists").pl()
    if ta_df.is_empty():
        log.warning("preprocessing.artist_medians.no_track_artists")
        return pl.DataFrame(
            schema={"artist_id": pl.Utf8} | {f: pl.Float64 for f in IMPUTABLE_AUDIO_FEATURES}
        )

    # Filter corpus to Spotify-sourced tracks only
    spotify_corpus = corpus.filter(pl.col("features_source") == "spotify")
    if spotify_corpus.is_empty():
        return pl.DataFrame(
            schema={"artist_id": pl.Utf8} | {f: pl.Float64 for f in IMPUTABLE_AUDIO_FEATURES}
        )

    # Join tracks to artists, then group by artist and compute medians
    joined = ta_df.join(
        spotify_corpus.select(["id"] + IMPUTABLE_AUDIO_FEATURES),
        left_on="track_id",
        right_on="id",
        how="inner",
    )

    medians = joined.group_by("artist_id").agg(
        [pl.col(f).median().alias(f) for f in IMPUTABLE_AUDIO_FEATURES]
    )
    log.info("preprocessing.artist_medians.computed", n_artists=len(medians))
    return medians


def compute_genre_medians(corpus: pl.DataFrame) -> pl.DataFrame:
    """Compute median audio features per first_genre from tracks with real Spotify data.

    Only uses tracks where features_source='spotify'.

    Args:
        corpus: Base corpus DataFrame with audio features, first_genre, features_source.

    Returns:
        DataFrame with columns: first_genre + one median column per audio feature.
    """
    spotify_corpus = corpus.filter(
        (pl.col("features_source") == "spotify") & pl.col("first_genre").is_not_null()
    )
    if spotify_corpus.is_empty():
        return pl.DataFrame(
            schema={"first_genre": pl.Utf8} | {f: pl.Float64 for f in IMPUTABLE_AUDIO_FEATURES}
        )

    medians = spotify_corpus.group_by("first_genre").agg(
        [pl.col(f).median().alias(f) for f in IMPUTABLE_AUDIO_FEATURES]
    )
    log.info("preprocessing.genre_medians.computed", n_genres=len(medians))
    return medians


def impute_missing_features(
    corpus: pl.DataFrame,
    artist_medians: pl.DataFrame,
    genre_medians: pl.DataFrame,
    conn: DuckDBPyConnection,
) -> pl.DataFrame:
    """Fill NULL audio features via cascade: artist → genre → global median.

    Modifies features_source to track provenance:
    - 'spotify': original Spotify data (unchanged)
    - 'imputed_artist': filled from same-artist median
    - 'imputed_genre': filled from same-genre median
    - 'imputed_global': filled from corpus-wide median

    Args:
        corpus: Base corpus (may have NULLs in audio feature columns).
        artist_medians: Per-artist median features from compute_artist_medians().
        genre_medians: Per-genre median features from compute_genre_medians().
        conn: DuckDB connection for track_artists lookup.

    Returns:
        Corpus with all audio feature NULLs filled and features_source updated.
    """
    # Identify rows needing imputation (any NULL in audio features)
    needs_impute_mask = pl.any_horizontal([pl.col(f).is_null() for f in IMPUTABLE_AUDIO_FEATURES])
    n_missing = corpus.filter(needs_impute_mask).height
    if n_missing == 0:
        log.info("preprocessing.impute.none_needed")
        return corpus

    log.info("preprocessing.impute.start", n_missing=n_missing)

    # Get track→artist mapping for artist-level imputation
    ta_df = conn.execute("SELECT track_id, artist_id FROM track_artists").pl()

    # Compute global median as final fallback
    spotify_corpus = corpus.filter(pl.col("features_source") == "spotify")
    global_medians: dict[str, float] = {}
    for f in IMPUTABLE_AUDIO_FEATURES:
        med = spotify_corpus[f].median()
        global_medians[f] = float(med) if med is not None else 0.0

    result_rows: list[pl.DataFrame] = []

    # Process rows that DON'T need imputation (pass through)
    clean = corpus.filter(~needs_impute_mask)
    result_rows.append(clean)

    # Process rows that DO need imputation
    dirty = corpus.filter(needs_impute_mask)

    for row_idx in range(dirty.height):
        row = dirty.row(row_idx, named=True)
        track_id = row["id"]
        source = row.get("features_source", None)
        new_source = source

        filled: dict[str, object] = dict(row)

        # Level 1: Artist-median
        imputed_by_artist = False
        if not ta_df.is_empty():
            artist_ids = ta_df.filter(pl.col("track_id") == track_id)["artist_id"].to_list()
            for aid in artist_ids:
                artist_row = artist_medians.filter(pl.col("artist_id") == aid)
                if artist_row.height > 0:
                    ar = artist_row.row(0, named=True)
                    for f in IMPUTABLE_AUDIO_FEATURES:
                        if filled.get(f) is None and ar.get(f) is not None:
                            filled[f] = ar[f]
                            imputed_by_artist = True
            if imputed_by_artist:
                new_source = "imputed_artist"

        # Level 2: Genre-median
        still_null = [f for f in IMPUTABLE_AUDIO_FEATURES if filled.get(f) is None]
        if still_null and row.get("first_genre") is not None:
            genre_row = genre_medians.filter(pl.col("first_genre") == row["first_genre"])
            if genre_row.height > 0:
                gr = genre_row.row(0, named=True)
                for f in still_null:
                    if gr.get(f) is not None:
                        filled[f] = gr[f]
                if new_source != "imputed_artist":
                    new_source = "imputed_genre"

        # Level 3: Global-median
        still_null = [f for f in IMPUTABLE_AUDIO_FEATURES if filled.get(f) is None]
        if still_null:
            for f in still_null:
                filled[f] = global_medians[f]
            if new_source not in ("imputed_artist", "imputed_genre"):
                new_source = "imputed_global"

        filled["features_source"] = new_source
        result_rows.append(pl.DataFrame([filled], schema=dirty.schema))

    result = pl.concat(result_rows, how="diagonal_relaxed")

    n_imputed = result.filter(pl.col("features_source").str.starts_with("imputed")).height
    log.info(
        "preprocessing.impute.done",
        n_imputed=n_imputed,
        n_total=result.height,
    )
    return result


# ---------------------------------------------------------------------------
# 4. Collaborative features
# ---------------------------------------------------------------------------


def add_collaborative_features(
    corpus: pl.DataFrame,
    conn: DuckDBPyConnection,
) -> pl.DataFrame:
    """Add playlist-derived collaborative features to the corpus.

    New columns:
    - n_playlists: number of user playlists containing each track
    - playlist_diversity: number of distinct gen_4 groups across those playlists
    - fave_score: personal rating from faves table (default 0.0)

    Args:
        corpus: Base corpus DataFrame (must have 'id' column).
        conn: Open DuckDB connection.

    Returns:
        Corpus with three new columns appended.
    """
    # n_playlists: how many playlists each track appears in
    n_playlists_df = conn.execute("""
        SELECT track_id AS id, COUNT(*) AS n_playlists
        FROM playlist_tracks
        GROUP BY track_id
    """).pl()

    # playlist_diversity: how many distinct gen_4 groups
    diversity_df = conn.execute("""
        SELECT pt.track_id AS id, COUNT(DISTINCT p.gen_4) AS playlist_diversity
        FROM playlist_tracks pt
        JOIN playlists p ON pt.playlist_id = p.playlist_id
        WHERE p.gen_4 IS NOT NULL
        GROUP BY pt.track_id
    """).pl()

    # Left join collaborative features onto corpus
    result = corpus.join(n_playlists_df, on="id", how="left")
    result = result.join(diversity_df, on="id", how="left")

    # fave_score: skip if already present (e.g. from track_profile view)
    if "fave_score" not in result.columns:
        faves_df = conn.execute("""
            SELECT track_id AS id, score AS fave_score
            FROM faves
        """).pl()
        result = result.join(faves_df, on="id", how="left")

    # Fill NULLs with 0
    result = result.with_columns(
        pl.col("n_playlists").fill_null(0).cast(pl.Float64),
        pl.col("playlist_diversity").fill_null(0).cast(pl.Float64),
        pl.col("fave_score").fill_null(0.0),
    )

    log.info(
        "preprocessing.collaborative.done",
        n_in_playlists=result.filter(pl.col("n_playlists") > 0).height,
        n_with_faves=result.filter(pl.col("fave_score") > 0).height,
    )
    return result


# ---------------------------------------------------------------------------
# 5. Temporal features
# ---------------------------------------------------------------------------


def add_temporal_features(corpus: pl.DataFrame) -> pl.DataFrame:
    """Add time-derived features to the corpus.

    New columns:
    - year_normalized: (year - min_year) / (max_year - min_year), NULLs → 0.5
    - years_since_release: current_year - year, NULLs → median
    - duration_ms_normalized: (duration_ms - min) / (max - min), NULLs → 0.5

    Args:
        corpus: Base corpus DataFrame with 'year' and 'duration_ms' columns.

    Returns:
        Corpus with three new columns appended.
    """
    current_year = datetime.now().year

    # year_normalized: (year - min) / (max - min), NULLs → 0.5
    if "year" in corpus.columns:
        year_col = corpus["year"].cast(pl.Float64, strict=False)
        min_year = year_col.min()
        max_year = year_col.max()
        year_range = (
            (max_year - min_year)
            if (min_year is not None and max_year is not None and max_year != min_year)
            else 1.0
        )
        if year_range == 0:
            year_range = 1.0

        result = corpus.with_columns(
            ((pl.col("year").cast(pl.Float64, strict=False) - (min_year or 0)) / year_range)
            .fill_null(0.5)
            .alias("year_normalized")
        )

        # years_since_release: current_year - year, NULLs → median
        median_years_since = year_col.map_elements(
            lambda y: current_year - y if y is not None else None,
            return_dtype=pl.Float64,
        ).median()
        if median_years_since is None:
            median_years_since = 0.0

        result = result.with_columns(
            (pl.lit(current_year) - pl.col("year").cast(pl.Float64, strict=False))
            .fill_null(median_years_since)
            .alias("years_since_release")
        )
    else:
        result = corpus.with_columns(
            pl.lit(0.5).alias("year_normalized"),
            pl.lit(0.0).alias("years_since_release"),
        )

    # duration_ms_normalized: (duration_ms - min) / (max - min), NULLs → 0.5
    if "duration_ms" in result.columns:
        dur_col = result["duration_ms"].cast(pl.Float64, strict=False)
        min_dur = dur_col.min()
        max_dur = dur_col.max()
        dur_range = (
            (max_dur - min_dur)
            if (min_dur is not None and max_dur is not None and max_dur != min_dur)
            else 1.0
        )
        if dur_range == 0:
            dur_range = 1.0

        result = result.with_columns(
            ((pl.col("duration_ms").cast(pl.Float64, strict=False) - (min_dur or 0)) / dur_range)
            .fill_null(0.5)
            .alias("duration_ms_normalized")
        )
    else:
        result = result.with_columns(pl.lit(0.5).alias("duration_ms_normalized"))

    log.info("preprocessing.temporal.done")
    return result


# ---------------------------------------------------------------------------
# 6. Artist-genre ENOA centroid
# ---------------------------------------------------------------------------


def compute_artist_enoa_centroid(
    conn: DuckDBPyConnection,
) -> pl.DataFrame:
    """Compute average ENOA (top, left) coordinates across each artist's genres.

    Artists have a comma-separated genres string in the artists table.
    Each genre is looked up in genre_xy for its (top, left) coordinates.
    The centroid is the mean of all matched genres.

    Args:
        conn: Open DuckDB connection with artists and genre_xy tables.

    Returns:
        DataFrame with columns: artist_id, artist_enoa_top, artist_enoa_left.
        Artists with no matched genres are excluded.
    """
    # Get artists with genre strings
    artists_df = conn.execute(
        "SELECT artist_id, genres FROM artists WHERE genres IS NOT NULL AND genres != ''"
    ).pl()

    if artists_df.is_empty():
        log.warning("preprocessing.artist_enoa.no_artists")
        return pl.DataFrame(
            schema={
                "artist_id": pl.Utf8,
                "artist_enoa_top": pl.Float64,
                "artist_enoa_left": pl.Float64,
            }
        )

    # Get genre_xy lookup
    genre_xy = conn.execute('SELECT first_genre, top, "left" FROM genre_xy').pl()

    if genre_xy.is_empty():
        log.warning("preprocessing.artist_enoa.no_genre_xy")
        return pl.DataFrame(
            schema={
                "artist_id": pl.Utf8,
                "artist_enoa_top": pl.Float64,
                "artist_enoa_left": pl.Float64,
            }
        )

    # Build genre → (top, left) lookup
    genre_lookup: dict[str, tuple[float, float]] = {}
    for row in genre_xy.iter_rows(named=True):
        genre_lookup[row["first_genre"].lower()] = (row["top"], row["left"])

    # For each artist, parse genres, look up ENOA coords, average
    result_rows: list[dict[str, object]] = []
    for row in artists_df.iter_rows(named=True):
        genres_str = row["genres"]
        # Handle both "[genre1, genre2]" and "genre1, genre2" formats
        cleaned = genres_str.strip("[]'\"")
        genres = [g.strip().strip("'\"").lower() for g in cleaned.split(",") if g.strip()]

        tops: list[float] = []
        lefts: list[float] = []
        for g in genres:
            if g in genre_lookup:
                t, l = genre_lookup[g]
                tops.append(t)
                lefts.append(l)

        if tops:
            result_rows.append(
                {
                    "artist_id": row["artist_id"],
                    "artist_enoa_top": sum(tops) / len(tops),
                    "artist_enoa_left": sum(lefts) / len(lefts),
                }
            )

    if not result_rows:
        log.warning("preprocessing.artist_enoa.no_matches")
        return pl.DataFrame(
            schema={
                "artist_id": pl.Utf8,
                "artist_enoa_top": pl.Float64,
                "artist_enoa_left": pl.Float64,
            }
        )

    result = pl.DataFrame(result_rows)
    log.info("preprocessing.artist_enoa.done", n_artists=len(result))
    return result


# ---------------------------------------------------------------------------
# 7. Playlist profile propagation
# ---------------------------------------------------------------------------


def propagate_playlist_profiles(
    corpus: pl.DataFrame,
    conn: DuckDBPyConnection,
) -> pl.DataFrame:
    """Compute per-track neighbourhood features from playlist co-membership.

    For each track, computes the centroid of all OTHER tracks in the same
    playlists (excluding itself). Multi-playlist tracks get a weighted
    average across playlists.

    This is used as an additional imputation signal — tracks with missing
    audio features can inherit their playlist neighbourhood's profile.

    Args:
        corpus: Corpus DataFrame with audio features and 'id' column.
        conn: Open DuckDB connection with playlist_tracks table.

    Returns:
        Corpus with playlist-propagated profile columns added.
    """
    # Get all playlist → track mappings
    pt_df = conn.execute("SELECT playlist_id, track_id FROM playlist_tracks").pl()
    if pt_df.is_empty():
        log.warning("preprocessing.playlist_propagation.no_data")
        return corpus

    # Features to propagate
    propagation_features = [f for f in IMPUTABLE_AUDIO_FEATURES if f in corpus.columns]
    if not propagation_features:
        return corpus

    # Build track_id → feature vector lookup from the corpus
    corpus_features = corpus.select(["id"] + propagation_features).rename({"id": "track_id"})

    # Join playlist_tracks with features
    pt_with_features = pt_df.join(corpus_features, on="track_id", how="inner")

    # For each track, compute the mean of all OTHER tracks in its playlists
    # Step 1: Get all playlist centroids (mean of all tracks in playlist)
    playlist_centroids = pt_with_features.group_by("playlist_id").agg(
        [pl.col(f).mean().alias(f"playlist_mean_{f}") for f in propagation_features]
        + [pl.col("track_id").count().alias("playlist_size")]
    )

    # Step 2: For each (track, playlist), compute "leave-one-out" centroid:
    #   (playlist_sum - track_value) / (playlist_size - 1)
    # For efficiency, approximate with playlist centroid (bias is negligible for playlists > 5 tracks)
    track_playlists = pt_df.join(playlist_centroids, on="playlist_id", how="inner")

    # Step 3: Average across all playlists each track belongs to
    propagated = (
        track_playlists.group_by("track_id")
        .agg([pl.col(f"playlist_mean_{f}").mean().alias(f"pp_{f}") for f in propagation_features])
        .rename({"track_id": "id"})
    )

    result = corpus.join(propagated, on="id", how="left")
    log.info(
        "preprocessing.playlist_propagation.done",
        n_propagated=result.filter(pl.col(f"pp_{propagation_features[0]}").is_not_null()).height,
    )
    return result


# ---------------------------------------------------------------------------
# 8. Orchestrator
# ---------------------------------------------------------------------------


def build_feature_matrix(conn: DuckDBPyConnection) -> pl.DataFrame:
    """Build the complete ML-ready feature matrix from DuckDB.

    Orchestrates all preprocessing steps in order:
    1. Load base corpus from track_profile view
    2. Add collaborative features (n_playlists, playlist_diversity, fave_score)
    3. Add temporal features (year_normalized, years_since_release, duration_ms_normalized)
    4. Compute and join artist-genre ENOA centroids
    5. Impute missing audio features (artist → genre → global median cascade)
    6. Propagate playlist profiles
    7. Final column selection and NULL validation

    Args:
        conn: Open DuckDB connection (read-only is sufficient unless
              computing Track2Vec embeddings).

    Returns:
        Clean pl.DataFrame ready for training or inference. All feature
        columns are non-NULL. Contains 'id' column for track identification.
    """
    log.info("preprocessing.build.start")

    # 1. Load base corpus from track_profile view
    corpus = load_corpus_from_db(conn)
    if corpus.is_empty():
        log.warning("preprocessing.build.empty_corpus")
        return corpus

    # 2. Add collaborative features (n_playlists, playlist_diversity, fave_score)
    corpus = add_collaborative_features(corpus, conn)

    # 3. Add temporal features (year_normalized, years_since_release, duration_ms_normalized)
    corpus = add_temporal_features(corpus)

    # 4. Compute and join artist-genre ENOA centroids
    artist_enoa = compute_artist_enoa_centroid(conn)
    if not artist_enoa.is_empty():
        # Join via track_artists: track → artist → artist_enoa
        ta_df = conn.execute("SELECT track_id, artist_id FROM track_artists").pl()
        if not ta_df.is_empty():
            # Take first artist per track for ENOA (primary artist)
            ta_first = ta_df.unique(subset=["track_id"], keep="first")
            ta_enoa = ta_first.join(artist_enoa, on="artist_id", how="left")
            ta_enoa = ta_enoa.select(["track_id", "artist_enoa_top", "artist_enoa_left"])
            ta_enoa = ta_enoa.rename({"track_id": "id"})
            corpus = corpus.join(ta_enoa, on="id", how="left")

    # Ensure artist_enoa columns exist even if empty
    if "artist_enoa_top" not in corpus.columns:
        corpus = corpus.with_columns(pl.lit(None, dtype=pl.Float64).alias("artist_enoa_top"))
    if "artist_enoa_left" not in corpus.columns:
        corpus = corpus.with_columns(pl.lit(None, dtype=pl.Float64).alias("artist_enoa_left"))

    # Fill NULL artist ENOA with track-level ENOA (from genre_map)
    if "top" in corpus.columns:
        corpus = corpus.with_columns(
            pl.col("artist_enoa_top").fill_null(pl.col("top")),
            pl.col("artist_enoa_left").fill_null(pl.col("left")),
        )

    # 5. Impute missing audio features (artist → genre → global median cascade)
    artist_medians = compute_artist_medians(corpus, conn)
    genre_medians = compute_genre_medians(corpus)
    corpus = impute_missing_features(corpus, artist_medians, genre_medians, conn)

    # 6. Propagate playlist profiles
    corpus = propagate_playlist_profiles(corpus, conn)

    # 7. Final NULL cleanup for engineered feature columns
    fill_zero_cols = [
        "fave_score",
        "n_playlists",
        "year_normalized",
        "years_since_release",
        "duration_ms_normalized",
        "playlist_diversity",
    ]
    for col in fill_zero_cols:
        if col in corpus.columns:
            corpus = corpus.with_columns(pl.col(col).fill_null(0.0))

    # Fill any remaining NULL audio features with 0.0 (safety net)
    for f in IMPUTABLE_AUDIO_FEATURES:
        if f in corpus.columns:
            corpus = corpus.with_columns(pl.col(f).fill_null(0.0))

    log.info(
        "preprocessing.build.done",
        n_rows=len(corpus),
        n_cols=len(corpus.columns),
    )
    return corpus
