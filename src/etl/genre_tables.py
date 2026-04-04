"""
Populate genre profile tables from existing DB data and external CSV.

Steps:
  1. track_genre   — from tracks + genre_map + genre_xy
  2. artist_genre  — aggregated from track_genre via track_artists
  3. playlist_genre — aggregated from track_genre via playlist_tracks
  4. external_tracks — from data/archived/spotify_train_data.csv

Run:
  PYTHONPATH=src uv run python -m etl.genre_tables
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from etl.db import get_connection, init_schema
from utils.logging import get_logger

log = get_logger(__name__)

ARCHIVED = Path(__file__).resolve().parents[2] / "data" / "archived"
EXTERNAL_CSV = Path(__file__).resolve().parents[2] / "data" / "spotify_train_data.csv"


# ── Step 1: track_genre ──────────────────────────────────────────────────────


def populate_track_genre(conn) -> None:
    """Build track_genre from tracks joined with genre_map and genre_xy.

    Priority:
    - genre_map match → genre_source = 'manual' (has full taxonomy + coords)
    - genre_xy match only → genre_source = 'lookup' (coords only, no taxonomy)
    - no match → row still inserted with nulls, genre_source = 'unknown'
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO track_genre
            (track_id, first_genre,
             gen_4, gen_6, gen_8, my_genre, sub_genre,
             top, "left", color,
             genre_source)
        SELECT
            t.track_id,
            t.first_genre,
            gm.gen_4,
            gm.gen_6,
            gm.gen_8,
            gm.my_genre,
            gm.sub_genre,
            COALESCE(gm.top,    xy.top)     AS top,
            COALESCE(gm."left", xy."left")  AS "left",
            COALESCE(gm.color,  xy.color)   AS color,
            CASE
                WHEN gm.first_genre IS NOT NULL THEN 'manual'
                WHEN xy.first_genre IS NOT NULL THEN 'lookup'
                ELSE 'unknown'
            END AS genre_source
        FROM tracks t
        LEFT JOIN genre_map gm ON t.first_genre = gm.first_genre
        LEFT JOIN genre_xy  xy ON t.first_genre = xy.first_genre
        """
    )

    total = conn.execute("SELECT COUNT(*) FROM track_genre").fetchone()[0]
    manual = conn.execute(
        "SELECT COUNT(*) FROM track_genre WHERE genre_source = 'manual'"
    ).fetchone()[0]
    lookup = conn.execute(
        "SELECT COUNT(*) FROM track_genre WHERE genre_source = 'lookup'"
    ).fetchone()[0]
    unknown = conn.execute(
        "SELECT COUNT(*) FROM track_genre WHERE genre_source = 'unknown'"
    ).fetchone()[0]
    no_coords = conn.execute("SELECT COUNT(*) FROM track_genre WHERE top IS NULL").fetchone()[0]

    log.info(
        "genre_tables.track_genre.done",
        total=total,
        manual=manual,
        lookup=lookup,
        unknown=unknown,
        no_coords=no_coords,
    )


# ── Step 2: artist_genre ─────────────────────────────────────────────────────


def _mode_agg(conn, group_col: str, value_col: str, source_table: str) -> pl.DataFrame:
    """Return mode of value_col grouped by group_col from a registered temp view."""
    return conn.execute(
        f"""
        SELECT {group_col}, {value_col}
        FROM (
            SELECT {group_col}, {value_col},
                   ROW_NUMBER() OVER (
                       PARTITION BY {group_col}
                       ORDER BY COUNT(*) DESC
                   ) AS rn
            FROM {source_table}
            WHERE {value_col} IS NOT NULL
            GROUP BY {group_col}, {value_col}
        )
        WHERE rn = 1
        """  # noqa: S608
    ).pl()


def populate_artist_genre(conn) -> None:
    """Derive artist_genre by aggregating track_genre through track_artists."""
    # Build a temp view of artist tracks with genre data
    conn.execute(
        """
        CREATE OR REPLACE TEMP VIEW _artist_track_genre AS
        SELECT
            ta.artist_id,
            tg.first_genre,
            tg.gen_4,
            tg.gen_6,
            tg.gen_8,
            tg.my_genre,
            tg.top,
            tg."left"
        FROM track_artists ta
        JOIN track_genre tg USING (track_id)
        """
    )

    # Centroids + track count
    base = conn.execute(
        """
        SELECT
            artist_id,
            AVG(top)    AS top,
            AVG("left") AS "left",
            COUNT(*)    AS track_count
        FROM _artist_track_genre
        GROUP BY artist_id
        """
    ).pl()

    # Mode per categorical field
    gen4 = _mode_agg(conn, "artist_id", "gen_4", "_artist_track_genre")
    gen6 = _mode_agg(conn, "artist_id", "gen_6", "_artist_track_genre")
    gen8 = _mode_agg(conn, "artist_id", "gen_8", "_artist_track_genre")
    my_genre = _mode_agg(conn, "artist_id", "my_genre", "_artist_track_genre")

    # Top first_genres by count → JSON array
    dominant = (
        conn.execute(
            """
        SELECT artist_id,
               LIST(first_genre ORDER BY cnt DESC)[1:5] AS dominant_genres
        FROM (
            SELECT artist_id, first_genre, COUNT(*) AS cnt
            FROM _artist_track_genre
            WHERE first_genre IS NOT NULL
            GROUP BY artist_id, first_genre
        )
        GROUP BY artist_id
        """
        )
        .pl()
        .with_columns(
            pl.col("dominant_genres").map_elements(
                lambda g: json.dumps(list(g)), return_dtype=pl.Utf8
            )
        )
    )

    # Join all aggregates
    result = (
        base.join(gen4.rename({"gen_4": "gen_4"}), on="artist_id", how="left")
        .join(gen6.rename({"gen_6": "gen_6"}), on="artist_id", how="left")
        .join(gen8.rename({"gen_8": "gen_8"}), on="artist_id", how="left")
        .join(my_genre.rename({"my_genre": "my_genre"}), on="artist_id", how="left")
        .join(dominant, on="artist_id", how="left")
        .select(
            [
                "artist_id",
                "gen_4",
                "gen_6",
                "gen_8",
                "my_genre",
                "top",
                "left",
                "dominant_genres",
                "track_count",
            ]
        )
    )

    conn.register("_artist_genre", result)
    conn.execute(
        """
        INSERT OR REPLACE INTO artist_genre
            (artist_id, gen_4, gen_6, gen_8, my_genre,
             top, "left", dominant_genres, track_count)
        SELECT artist_id, gen_4, gen_6, gen_8, my_genre,
               top, "left", dominant_genres, track_count
        FROM _artist_genre
        """
    )
    log.info("genre_tables.artist_genre.done", n=len(result))


# ── Step 3: playlist_genre ───────────────────────────────────────────────────


def populate_playlist_genre(conn) -> None:
    """Derive playlist_genre by aggregating track_genre through playlist_tracks."""
    conn.execute(
        """
        CREATE OR REPLACE TEMP VIEW _playlist_track_genre AS
        SELECT
            pt.playlist_id,
            tg.first_genre,
            tg.gen_4,
            tg.gen_6,
            tg.gen_8,
            tg.top,
            tg."left"
        FROM playlist_tracks pt
        JOIN track_genre tg USING (track_id)
        """
    )

    base = conn.execute(
        """
        SELECT
            playlist_id,
            AVG(top)    AS top,
            AVG("left") AS "left",
            COUNT(*)    AS track_count
        FROM _playlist_track_genre
        GROUP BY playlist_id
        """
    ).pl()

    gen4 = _mode_agg(conn, "playlist_id", "gen_4", "_playlist_track_genre")
    gen6 = _mode_agg(conn, "playlist_id", "gen_6", "_playlist_track_genre")
    gen8 = _mode_agg(conn, "playlist_id", "gen_8", "_playlist_track_genre")

    # genre counts for top/other split
    genre_counts = conn.execute(
        """
        SELECT playlist_id,
               LIST(first_genre ORDER BY cnt DESC) AS genres_ranked
        FROM (
            SELECT playlist_id, first_genre, COUNT(*) AS cnt
            FROM _playlist_track_genre
            WHERE first_genre IS NOT NULL
            GROUP BY playlist_id, first_genre
        )
        GROUP BY playlist_id
        """
    ).pl()

    top_other = genre_counts.with_columns(
        [
            pl.col("genres_ranked")
            .map_elements(lambda g: json.dumps(list(g)[:5]), return_dtype=pl.Utf8)
            .alias("top_genres"),
            pl.col("genres_ranked")
            .map_elements(lambda g: json.dumps(list(g)[5:]), return_dtype=pl.Utf8)
            .alias("other_genres"),
        ]
    ).drop("genres_ranked")

    result = (
        base.join(gen4, on="playlist_id", how="left")
        .join(gen6, on="playlist_id", how="left")
        .join(gen8, on="playlist_id", how="left")
        .join(top_other, on="playlist_id", how="left")
        .select(
            [
                "playlist_id",
                "gen_4",
                "gen_6",
                "gen_8",
                "top_genres",
                "other_genres",
                "top",
                "left",
                "track_count",
            ]
        )
    )

    conn.register("_playlist_genre", result)
    conn.execute(
        """
        INSERT OR REPLACE INTO playlist_genre
            (playlist_id, gen_4, gen_6, gen_8,
             top_genres, other_genres,
             top, "left", track_count)
        SELECT playlist_id, gen_4, gen_6, gen_8,
               top_genres, other_genres,
               top, "left", track_count
        FROM _playlist_genre
        """
    )
    log.info("genre_tables.playlist_genre.done", n=len(result))


# ── Step 4: external_tracks ──────────────────────────────────────────────────


def load_external_tracks(conn) -> None:
    """Load 595k Spotify training corpus into external_tracks."""
    if not EXTERNAL_CSV.exists():
        log.warning("genre_tables.external_tracks.missing", path=str(EXTERNAL_CSV))
        return

    log.info("genre_tables.external_tracks.loading", path=str(EXTERNAL_CSV))
    df = (
        pl.scan_csv(
            EXTERNAL_CSV,
            null_values=["", "NA", "NaN"],
            schema_overrides={
                "popularity": pl.Float64,
                "year": pl.Int32,
                "duration_ms": pl.Int64,
                "time_signature": pl.Int32,
                "key": pl.Int32,
                "mode": pl.Int32,
            },
        )
        .rename({"id": "track_id"})
        .select(
            [
                "track_id",
                "track_name",
                "artist_names",
                "popularity",
                "release_date",
                "year",
                "decade",
                "first_genre",
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
                "top",
                "left",
                "color",
                "y_target",
            ]
        )
        .unique("track_id")
        .collect()
    )

    conn.register("_external", df)
    conn.execute(
        """
        INSERT OR IGNORE INTO external_tracks
        SELECT track_id, track_name, artist_names, popularity,
               release_date, year, decade, first_genre,
               danceability, energy, loudness, speechiness,
               acousticness, instrumentalness, liveness, valence,
               tempo, duration_ms, time_signature, key, mode,
               key_labels, mode_labels, key_mode,
               top, "left", color, y_target
        FROM _external
        """
    )
    n = conn.execute("SELECT COUNT(*) FROM external_tracks").fetchone()[0]
    log.info("genre_tables.external_tracks.done", n=n)


# ── Entrypoint ───────────────────────────────────────────────────────────────


def main() -> None:
    conn = get_connection()
    init_schema(conn)

    log.info("genre_tables.start")
    populate_track_genre(conn)
    populate_artist_genre(conn)
    populate_playlist_genre(conn)
    load_external_tracks(conn)

    log.info(
        "genre_tables.done",
        track_genre=conn.execute("SELECT COUNT(*) FROM track_genre").fetchone()[0],
        artist_genre=conn.execute("SELECT COUNT(*) FROM artist_genre").fetchone()[0],
        playlist_genre=conn.execute("SELECT COUNT(*) FROM playlist_genre").fetchone()[0],
        external_tracks=conn.execute("SELECT COUNT(*) FROM external_tracks").fetchone()[0],
    )
    conn.close()


if __name__ == "__main__":
    main()
