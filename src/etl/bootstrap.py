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
from pathlib import Path

import polars as pl

from etl.db import get_connection, init_schema
from utils.logging import get_logger

log = get_logger(__name__)

ARCHIVED = Path("data/archived")


def _parse_list(val: str) -> list[str]:
    """Parse a stringified Python list like \"['a', 'b']\" → ['a', 'b']."""
    try:
        result = ast.literal_eval(val)
        return result if isinstance(result, list) else [str(result)]
    except Exception:
        return [val] if val else []


def load_playlists(conn) -> None:
    path = ARCHIVED / "my_playlists.csv"
    if not path.exists():
        log.warning("bootstrap.playlists.missing", path=str(path))
        return
    df = pl.read_csv(path).drop("")
    conn.register("_playlists", df)
    conn.execute(
        """
        INSERT OR IGNORE INTO playlists (playlist_id, playlist_name, gen_4, gen_6, gen_8, top_genres, other_genres)
        SELECT playlist_id, playlist_name, gen_4, gen_6, gen_8, top_genres, other_genres
        FROM _playlists
    """
    )
    log.info("bootstrap.playlists.done", n=len(df))


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
        INSERT OR IGNORE INTO artists
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
    conn.execute("INSERT OR IGNORE INTO audio_features SELECT * FROM _af")
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

    # ── track_artists (expand stringified list) ──────────────────────────────
    rows = []
    for row in df.select(["id", "artist_ids"]).unique("id").iter_rows(named=True):
        for aid in _parse_list(str(row["artist_ids"])):
            aid = aid.strip()
            if aid:
                rows.append({"track_id": row["id"], "artist_id": aid})
    if rows:
        ta = pl.DataFrame(rows).unique(["track_id", "artist_id"])
        conn.register("_ta", ta)
        conn.execute("INSERT OR IGNORE INTO track_artists SELECT * FROM _ta")
        log.info("bootstrap.track_artists.done", n=len(ta))


def main() -> None:
    conn = get_connection()
    init_schema(conn)

    load_playlists(conn)
    load_genre_map(conn)
    load_enoa_coordinates(conn)
    load_artists(conn)
    load_faves(conn)
    load_playlist_tracks(conn)

    # Quick sanity check
    n_tracks = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    n_genres = conn.execute("SELECT COUNT(*) FROM genre_map").fetchone()[0]
    n_profile = conn.execute("SELECT COUNT(*) FROM track_profile").fetchone()[0]
    print(
        f"\nDB ready: {n_tracks} tracks, {n_genres} genre mappings, {n_profile} enriched profiles"
    )
    print("Location: data/listen_wiseer.db")
    conn.close()


if __name__ == "__main__":
    main()
