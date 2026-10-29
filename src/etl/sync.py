"""
Incremental enrichment of the archived library: Last.fm genre tags → genre profiles.

The Spotify playlist/track/feature sync was removed with the Spotify client (S5);
the archived tables are frozen and only enriched from free sources now.

Run:
  PYTHONPATH=src uv run python -m etl.sync
  make data-sync
"""

from __future__ import annotations

from etl.db import get_connection, init_schema
from etl.lastfm import fetch_genres_for_tracks
from utils.config import settings
from utils.logging import configure_logging, get_logger

log = get_logger(__name__)


def sync_lastfm_genres(conn, limit: int | None = None) -> int:
    """Fetch Last.fm genre tags for tracks missing first_genre.

    Matches returned tags against the genre_xy table (6k+ ENOA genres).
    Writes first_genre to tracks and inserts a stub audio_features row
    flagged features_source='lastfm' so feature engineering can derive
    proxies from ENOA coordinates.

    Args:
        conn: DuckDB connection (read-write).
        limit: Cap number of tracks to process this run (None = no limit).

    Returns:
        Number of tracks where a genre match was found and written.
    """
    api_key = settings.last_fm_api_key
    if not api_key:
        log.warning("sync.lastfm.skip", reason="LAST_FM_API_KEY not set")
        return 0

    # Load genre_xy set for tag matching
    genre_xy_rows = conn.execute("SELECT first_genre FROM genre_xy").fetchall()
    genre_xy_set: set[str] = {row[0].lower() for row in genre_xy_rows}
    if not genre_xy_set:
        log.warning("sync.lastfm.skip", reason="genre_xy table is empty — run bootstrap first")
        return 0

    track_rows = conn.execute(
        """
        SELECT
            t.track_id,
            t.track_name,
            COALESCE(
                (SELECT a.artist_name
                 FROM track_artists ta
                 JOIN artists a USING (artist_id)
                 WHERE ta.track_id = t.track_id
                   AND a.artist_name IS NOT NULL
                 LIMIT 1),
                ''
            ) AS primary_artist_name
        FROM tracks t
        WHERE t.first_genre IS NULL
        ORDER BY t.track_id
        """
    ).fetchall()

    if limit is not None:
        track_rows = track_rows[:limit]

    total_missing = conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE first_genre IS NULL"
    ).fetchone()[0]
    log.info(
        "sync.lastfm.start", total_missing=total_missing, processing=len(track_rows), limit=limit
    )

    if not track_rows:
        return 0

    tracks_for_fetch = [
        {
            "track_id": row[0],
            "track_name": row[1],
            "artist_name": row[2] if row[2] else row[1],
        }
        for row in track_rows
    ]

    genre_map = fetch_genres_for_tracks(tracks_for_fetch, api_key, genre_xy_set)

    matched = 0
    for track_id, genre in genre_map.items():
        if genre is None:
            continue
        # Write first_genre to tracks
        conn.execute(
            "UPDATE tracks SET first_genre = ? WHERE track_id = ?",
            [genre, track_id],
        )
        # Insert stub audio_features row flagged as lastfm so feature engineering
        # can derive proxies from ENOA coordinates (numeric fields left NULL)
        conn.execute(
            """
            INSERT OR IGNORE INTO audio_features (track_id, features_source)
            VALUES (?, 'lastfm')
            """,
            [track_id],
        )
        matched += 1

    log.info("sync.lastfm.done", processed=len(track_rows), matched=matched)
    return matched


def sync_genre_profiles(conn) -> None:
    """Refresh track_genre, artist_genre, and playlist_genre from current DB state.

    Runs after lastfm genre sync so newly tagged tracks get genre profiles assigned.
    Uses genre_map (manual taxonomy) and genre_xy (ENOA coordinates) as lookup sources.
    Tracks with no match are written with genre_source='unknown' for later model inference.
    """
    from etl.genre_tables import (
        populate_artist_genre,
        populate_playlist_genre,
        populate_track_genre,
    )

    populate_track_genre(conn)
    populate_artist_genre(conn)
    populate_playlist_genre(conn)
    log.info("sync.genre_profiles.done")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Last.fm genre enrichment → genre profiles")
    parser.add_argument(
        "--lastfm-limit",
        type=int,
        default=None,
        metavar="N",
        help="Max tracks to fetch Last.fm genre tags for (default: no limit)",
    )
    args = parser.parse_args()

    configure_logging()
    conn = get_connection()
    init_schema(conn)
    sync_lastfm_genres(conn, limit=args.lastfm_limit)
    sync_genre_profiles(conn)
    conn.close()


if __name__ == "__main__":
    main()
