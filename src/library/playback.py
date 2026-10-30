"""
Playback resolution with a DuckDB cache for YouTube video IDs (search costs 100 of
10k daily quota units). Deezer previews are signed and expire, so never cached.
"""

from datetime import datetime

import duckdb

from etl.db import fetch_one
from etl.history import track_key
from library.downloads import local_path
from sources import youtube
from sources.http import SourceClient
from sources.playable import resolve_playable
from sources.schemas import PlayableTrack
from utils.exceptions import SourceError
from utils.logging import get_logger

log = get_logger(__name__)


def _cached_video_id(conn: duckdb.DuckDBPyConnection, key: str) -> str | None:
    """'' = searched before, nothing found; None = never searched."""
    row = fetch_one(conn, "SELECT youtube_video_id FROM playable_cache WHERE track_key = ?", [key])
    return None if row is None else row[0] or ""


def playable(
    artist: str,
    title: str,
    *,
    conn: duckdb.DuckDBPyConnection | None = None,
    deezer_client: SourceClient | None = None,
    youtube_client: SourceClient | None = None,
) -> PlayableTrack:
    """Resolve playback for a track, looking up / caching its YouTube video when ``conn``."""
    if conn is None:
        return resolve_playable(
            artist, title, deezer_client=deezer_client, youtube_client=youtube_client
        )

    key = track_key(artist, title)
    video_id = _cached_video_id(conn, key)
    yt = youtube_client or youtube.default_client()
    if video_id is None and yt is not None:
        try:
            video_id = youtube.find_video_id(artist, title, client=yt) or ""
        except SourceError as exc:
            log.warning("playback.youtube_failed", artist=artist, title=title, error=str(exc))
        else:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO playable_cache VALUES (?, ?, ?)",
                    [key, video_id, datetime.now()],
                )
            except duckdb.InvalidInputException:  # read-only conn (MCP server): no caching
                log.debug("playback.cache_write_skipped", artist=artist, title=title)
    p = resolve_playable(
        artist,
        title,
        deezer_client=deezer_client,
        video_id=video_id or None,
        search_youtube=False,
    )
    return p.model_copy(update={"local_path": local_path(conn, artist, title) or ""})
