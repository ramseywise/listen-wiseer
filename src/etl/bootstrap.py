"""
Bootstrap DuckDB from archived CSV files.

Loads:
  data/archived/playlists/*.csv      → tracks, audio_features, playlist_tracks
  data/archived/genres/genre_map.csv → genre_map
  data/archived/api/artists.csv      → artists
  data/archived/faves.csv            → faves
  data/archived/my_playlists.csv     → playlists

Run:
  PYTHONPATH=src uv run python -m etl.bootstrap
  make init-db
"""

import ast
import tomllib
from pathlib import Path

import polars as pl

from etl.db import get_connection, init_schema
from paths import PLAYLIST_CONFIG_PATH
from utils.logging import get_logger

log = get_logger(__name__)

ARCHIVED = Path(__file__).resolve().parents[2] / "data" / "archived"


def _load_playlist_status_config() -> dict[str, str]:
    """Return mapping of playlist_name → status from playlist_status.toml."""
    if not PLAYLIST_CONFIG_PATH.exists():
        log.warning("bootstrap.playlist_config.missing", path=str(PLAYLIST_CONFIG_PATH))
        return {}
    with PLAYLIST_CONFIG_PATH.open("rb") as fh:
        raw = tomllib.load(fh)
    return {
        name: attrs.get("status", "excluded") for name, attrs in raw.get("playlists", {}).items()
    }


def _parse_list(val: str) -> list[str]:
    """Parse artist_ids — handles Python list syntax or plain comma-separated strings.

    Examples:
        "['a', 'b']"  → ['a', 'b']
        "a, b"        → ['a', 'b']
        "a"           → ['a']
    """
    try:
        result = ast.literal_eval(val)
        return [s.strip() for s in result] if isinstance(result, list) else [str(result).strip()]
    except Exception:
        # Plain comma-separated string (e.g. "id1, id2")
        parts = [s.strip() for s in val.split(",") if s.strip()]
        return parts if parts else []


def load_playlists(conn) -> None:
    path = ARCHIVED / "my_playlists.csv"
    if not path.exists():
        log.warning("bootstrap.playlists.missing", path=str(path))
        return
    name_config = _load_playlist_status_config()
    df = pl.read_csv(path).drop("")
    df = df.with_columns(
        pl.col("playlist_name")
        .map_elements(lambda n: name_config.get(n, "excluded"), return_dtype=pl.Utf8)
        .alias("status")
    )
    conn.register("_playlists", df)
    conn.execute(
        """
        INSERT INTO playlists (playlist_id, playlist_name, status, gen_4, gen_6, gen_8, top_genres, other_genres)
        SELECT playlist_id, playlist_name, status, gen_4, gen_6, gen_8, top_genres, other_genres
        FROM _playlists
        ON CONFLICT (playlist_id) DO UPDATE SET
            playlist_name = excluded.playlist_name,
            status        = excluded.status
    """
    )
    by_status = df.group_by("status").len().sort("status")
    log.info("bootstrap.playlists.done", n=len(df), by_status=by_status.to_dicts())


def load_genre_map(conn) -> None:
    path = ARCHIVED / "genres/genre_map.csv"
    if not path.exists():
        log.warning("bootstrap.genre_map.missing", path=str(path))
        return
    df = pl.read_csv(path).drop("")
    conn.register("_genre_map", df)
    conn.execute(
        """
        INSERT OR IGNORE INTO genre_map (first_genre, gen_4, gen_6, gen_8, my_genre, sub_genre)
        SELECT first_genre, gen_4, gen_6, gen_8, my_genre, sub_genre
        FROM _genre_map
    """
    )
    log.info("bootstrap.genre_map.done", n=len(df))


def load_artists(conn) -> None:
    path = ARCHIVED / "api/artists.csv"
    if not path.exists():
        log.warning("bootstrap.artists.missing", path=str(path))
        return
    df = pl.read_csv(path, infer_schema_length=2000, schema_overrides={"popularity": pl.Utf8})
    cols = [c for c in df.columns if c not in ("", "0")]
    df = df.select(cols).with_columns(
        pl.col("popularity").str.extract(r"(\d+\.?\d*)", 0).cast(pl.Float64, strict=False)
    )
    conn.register("_artists", df)
    conn.execute(
        """
        INSERT OR IGNORE INTO artists (artist_id, popularity, genres)
        SELECT artist_id, popularity, genre
        FROM _artists
    """
    )
    log.info("bootstrap.artists.done", n=len(df))


def load_enoa_coordinates(conn) -> None:
    """Enrich genre_map with ENOA top/left/color from genres/genre_xy.csv."""
    path = ARCHIVED / "genres/genre_xy.csv"
    if not path.exists():
        log.warning("bootstrap.enoa.missing", path=str(path))
        return
    df = pl.read_csv(path)
    if "" in df.columns:
        df = df.drop("")
    conn.register("_enoa", df)
    conn.execute(
        """
        UPDATE genre_map
        SET top   = e.top,
            "left" = e."left",
            color  = e.color
        FROM _enoa e
        WHERE genre_map.first_genre = e.first_genre
    """
    )
    updated = conn.execute("SELECT COUNT(*) FROM genre_map WHERE top IS NOT NULL").fetchone()[0]
    log.info("bootstrap.enoa.done", n_updated=updated)


def load_genre_xy(conn) -> None:
    """Load full ENOA genre_xy table (6k+ genres → top/left/color).

    Separate from genre_map — covers all known genres for Last.fm tag matching,
    not just the curated subset in genre_map.csv.
    """
    path = ARCHIVED / "genres/genre_xy.csv"
    if not path.exists():
        log.warning("bootstrap.genre_xy.missing", path=str(path))
        return
    df = pl.read_csv(path)
    if "" in df.columns:
        df = df.drop("")
    df = df.select(["first_genre", "top", "left", "color"]).unique("first_genre")
    conn.register("_genre_xy", df)
    conn.execute(
        """
        INSERT OR IGNORE INTO genre_xy (first_genre, top, "left", color)
        SELECT first_genre, top, "left", color FROM _genre_xy
    """
    )
    n = conn.execute("SELECT COUNT(*) FROM genre_xy").fetchone()[0]
    log.info("bootstrap.genre_xy.done", n=n)


def load_faves(conn) -> None:
    path = ARCHIVED / "faves.csv"
    if not path.exists():
        log.warning("bootstrap.faves.missing", path=str(path))
        return
    df = pl.read_csv(path).drop("").rename({"id": "track_id", "faves": "score"})
    conn.register("_faves", df)
    conn.execute("INSERT OR IGNORE INTO faves SELECT track_id, score FROM _faves")
    log.info("bootstrap.faves.done", n=len(df))


def load_playlist_tracks(conn) -> None:
    """Load all per-playlist CSVs — the richest source (tracks + audio features joined)."""
    playlist_dir = ARCHIVED / "playlists"
    files = sorted(playlist_dir.glob("*.csv"))
    if not files:
        log.warning("bootstrap.playlist_tracks.missing", path=str(playlist_dir))
        return

    str_cols = {
        "popularity": pl.Utf8,
        "year": pl.Utf8,
        "key": pl.Utf8,
        "mode": pl.Utf8,
        "time_signature": pl.Utf8,
        "duration_ms": pl.Utf8,
    }
    all_dfs = []
    for f in files:
        try:
            df = pl.read_csv(f, infer_schema_length=2000, schema_overrides=str_cols)
            all_dfs.append(df)
        except Exception as e:
            log.warning("bootstrap.playlist_csv.error", file=f.name, error=str(e))

    if not all_dfs:
        return

    df = pl.concat(all_dfs, how="diagonal").drop("")

    # ── tracks ──────────────────────────────────────────────────────────────
    tracks_df = (
        df.select(
            [
                "id",
                "track_name",
                "release_date",
                "popularity",
                "first_genre",
                "genre_cat",
                "year",
                "decade",
            ]
        )
        .rename({"id": "track_id"})
        .unique("track_id")
        .with_columns(
            pl.col("popularity").str.extract(r"(\d+\.?\d*)", 0).cast(pl.Float64, strict=False),
            pl.col("year").str.extract(r"(\d{4})", 0).cast(pl.Int32, strict=False),
        )
    )

    conn.register("_tracks", tracks_df)
    conn.execute(
        """
        INSERT OR IGNORE INTO tracks (track_id, track_name, release_date, year, decade, popularity, first_genre, genre_cat)
        SELECT track_id, track_name, release_date, year, decade, popularity, first_genre, genre_cat
        FROM _tracks
    """
    )
    log.info("bootstrap.tracks.done", n=len(tracks_df))

    # ── audio_features ───────────────────────────────────────────────────────
    af_cols = [
        "id",
        "danceability",
        "energy",
        "loudness",
        "speechiness",
        "acousticness",
        "instrumentalness",
        "liveness",
        "valence",
        "tempo",
        "duration_ms",
        "time_signature",
        "key",
        "mode",
        "key_labels",
        "mode_labels",
        "key_mode",
    ]
    float_af = [
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
    int_af = ["duration_ms", "time_signature", "key", "mode"]
    af_df = (
        df.select([c for c in af_cols if c in df.columns])
        .rename({"id": "track_id"})
        .unique("track_id")
        .with_columns(
            [pl.col(c).cast(pl.Float64, strict=False) for c in float_af if c in df.columns]
            + [
                pl.col(c).str.extract(r"(-?\d+)", 0).cast(pl.Int64, strict=False)
                for c in int_af
                if c in df.columns
            ]
        )
    )
    conn.register("_af", af_df)
    conn.execute(
        """
        INSERT OR IGNORE INTO audio_features
            (track_id, danceability, energy, loudness, speechiness, acousticness,
             instrumentalness, liveness, valence, tempo, duration_ms, time_signature,
             key, mode, key_labels, mode_labels, key_mode, features_source)
        SELECT track_id, danceability, energy, loudness, speechiness, acousticness,
               instrumentalness, liveness, valence, tempo, duration_ms, time_signature,
               key, mode, key_labels, mode_labels, key_mode, 'spotify'
        FROM _af
        """
    )
    log.info("bootstrap.audio_features.done", n=len(af_df))

    # ── playlist_tracks (junction) ───────────────────────────────────────────
    pt_df = (
        df.select(["playlist_id", "id"])
        .rename({"id": "track_id"})
        .unique(["playlist_id", "track_id"])
    )
    conn.register("_pt", pt_df)
    conn.execute("INSERT OR IGNORE INTO playlist_tracks SELECT * FROM _pt")
    log.info("bootstrap.playlist_tracks.done", n=len(pt_df))

    # ── track_artists (expand stringified list) + artist names ──────────────
    ta_rows: list[dict] = []
    name_rows: list[dict] = []
    for row in df.select(["id", "artist_ids", "artist_names"]).unique("id").iter_rows(named=True):
        ids = _parse_list(str(row["artist_ids"]))
        names = _parse_list(str(row["artist_names"]))
        for i, aid in enumerate(ids):
            aid = aid.strip()
            if not aid:
                continue
            ta_rows.append({"track_id": row["id"], "artist_id": aid})
            name = names[i].strip() if i < len(names) else ""
            if name:
                name_rows.append({"artist_id": aid, "artist_name": name})
    if ta_rows:
        ta = pl.DataFrame(ta_rows).unique(["track_id", "artist_id"])
        conn.register("_ta", ta)
        conn.execute("INSERT OR IGNORE INTO track_artists SELECT * FROM _ta")
        log.info("bootstrap.track_artists.done", n=len(ta))
    if name_rows:
        an = pl.DataFrame(name_rows).unique("artist_id")
        conn.register("_an", an)
        conn.execute(
            """
            INSERT INTO artists (artist_id, artist_name)
            SELECT artist_id, artist_name FROM _an
            ON CONFLICT (artist_id) DO UPDATE SET
                artist_name = CASE WHEN artists.artist_name IS NULL
                                   THEN excluded.artist_name
                                   ELSE artists.artist_name END
            """
        )
        log.info("bootstrap.artist_names.done", n=len(an))


def _train_if_needed() -> None:
    """Run model training when no classifier .pkl files exist in models/."""
    import subprocess
    import sys

    from paths import MODELS_DIR

    if list(MODELS_DIR.glob("*.pkl")):
        log.info("bootstrap.train.skip", reason="models already present")
        return

    log.info("bootstrap.train.start", models_dir=str(MODELS_DIR))
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "recommend.train"],
        check=False,
    )
    if result.returncode != 0:
        log.error("bootstrap.train.failed", returncode=result.returncode)
    else:
        log.info("bootstrap.train.done")


def main() -> None:
    conn = get_connection()
    init_schema(conn)

    load_playlists(conn)
    load_genre_map(conn)
    load_enoa_coordinates(conn)
    load_genre_xy(conn)
    load_artists(conn)
    load_faves(conn)
    load_playlist_tracks(conn)

    n_tracks = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    n_genres = conn.execute("SELECT COUNT(*) FROM genre_map").fetchone()[0]
    n_profile = conn.execute("SELECT COUNT(*) FROM track_profile").fetchone()[0]
    from etl.db import DB_PATH

    log.info(
        "bootstrap.db.ready",
        n_tracks=n_tracks,
        n_genres=n_genres,
        n_profile=n_profile,
        db_path=str(DB_PATH),
    )
    conn.close()

    _train_if_needed()


if __name__ == "__main__":
    main()
