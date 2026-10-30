"""
Resolve played tracks to MusicBrainz + Deezer IDs → ``track_xref``.

Order: MusicBrainz search (artist + title) → MusicBrainz Spotify-URL lookup
(low coverage, only when spotify_id is known) → Deezer search for deezer_id / ISRC.

Resumable: tracks already in track_xref are skipped; unmatched rows are stored with
mbid NULL and only retried with --retry-unmatched. Transport errors leave no row,
so the track is retried next run. MusicBrainz caps at 1 req/s → ~1.5–3 s/track;
bound runs with --limit / --min-plays.

Run:
  PYTHONPATH=src uv run python -m etl.resolve --limit 500
  make resolve-ids
"""

import argparse
from datetime import datetime

import duckdb
import polars as pl

from etl.db import get_connection, init_schema
from sources import deezer
from sources import musicbrainz as mb
from sources.http import SourceClient
from utils.exceptions import SourceError
from utils.logging import get_logger

log = get_logger(__name__)

MIN_MS_PLAYED = 30_000  # Spotify's own "counts as a stream" threshold


def pending_tracks(
    conn: duckdb.DuckDBPyConnection,
    *,
    min_plays: int = 2,
    limit: int | None = None,
    retry_unmatched: bool = False,
) -> pl.DataFrame:
    """Tracks with ≥ min_plays real plays and no track_xref row yet, most-played first."""
    sql = """
        SELECT track_key,
               any_value(artist_name) AS artist_name,
               any_value(track_name)  AS track_name,
               max(spotify_id)        AS spotify_id,
               count(*)               AS n_plays
        FROM plays
        WHERE ms_played >= ?
          AND track_key NOT IN (
              SELECT track_key FROM track_xref
              WHERE resolved_at IS NOT NULL AND (NOT ? OR mbid IS NOT NULL)
          )
        GROUP BY track_key
        HAVING count(*) >= ?
        ORDER BY n_plays DESC, track_key
        LIMIT ?
    """
    no_limit = 2**62
    params = [MIN_MS_PLAYED, retry_unmatched, min_plays, no_limit if limit is None else limit]
    return conn.sql(sql, params=params).pl()


def resolve_track(
    artist: str,
    title: str,
    spotify_id: str | None = None,
    *,
    mb_client: SourceClient | None = None,
    deezer_client: SourceClient | None = None,
) -> dict:
    """IDs for one track. Raises SourceError on transport failure."""
    rec = mb.best_match(artist, title, client=mb_client)
    mbid = rec.mbid if rec else None
    method = "search" if rec else None
    if mbid is None and spotify_id:
        mbid = mb.lookup_spotify_track(spotify_id, client=mb_client)
        method = "spotify_url" if mbid else None

    dz = deezer.find_track(artist, title, client=deezer_client) or {}
    return {
        "mbid": mbid,
        "artist_mbids": rec.artist_mbids if rec else [],
        "mb_score": rec.score if rec else None,
        "mb_method": method,
        "deezer_id": dz.get("id"),
        "isrc": dz.get("isrc"),
    }


def resolve_pending(
    conn: duckdb.DuckDBPyConnection,
    *,
    min_plays: int = 2,
    limit: int | None = None,
    retry_unmatched: bool = False,
    mb_client: SourceClient | None = None,
    deezer_client: SourceClient | None = None,
) -> tuple[int, int]:
    """Resolve pending tracks, writing one track_xref row each. Returns (written, matched)."""
    todo = pending_tracks(conn, min_plays=min_plays, limit=limit, retry_unmatched=retry_unmatched)
    log.info("resolve.start", pending=len(todo))
    written = matched = 0
    for row in todo.iter_rows(named=True):
        try:
            ids = resolve_track(
                row["artist_name"],
                row["track_name"],
                row["spotify_id"],
                mb_client=mb_client,
                deezer_client=deezer_client,
            )
        except SourceError as exc:
            log.warning("resolve.source_error", track_key=row["track_key"], error=str(exc))
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO track_xref
                (track_key, artist_name, track_name, spotify_id, mbid, artist_mbids,
                 mb_score, mb_method, deezer_id, isrc, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                row["track_key"],
                row["artist_name"],
                row["track_name"],
                row["spotify_id"],
                ids["mbid"],
                ids["artist_mbids"],
                ids["mb_score"],
                ids["mb_method"],
                ids["deezer_id"],
                ids["isrc"],
                datetime.now(),
            ],
        )
        written += 1
        matched += ids["mbid"] is not None
        if written % 50 == 0:
            log.info("resolve.progress", written=written, matched=matched, pending=len(todo))
    log.info("resolve.done", written=written, matched=matched)
    return written, matched


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve played tracks to MusicBrainz/Deezer IDs")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-plays", type=int, default=2)
    parser.add_argument("--retry-unmatched", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    init_schema(conn)
    resolve_pending(
        conn, min_plays=args.min_plays, limit=args.limit, retry_unmatched=args.retry_unmatched
    )
    conn.close()


if __name__ == "__main__":
    main()
