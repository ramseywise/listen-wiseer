"""Spotify-free discovery, playback and playlists (saved to Navidrome, exported as JSPF).

Tools return content + artifact: the artifact carries structured tracks so
format_response can hand them to the UI (play buttons, save-as-playlist).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb
from langchain_core.tools import StructuredTool
from langgraph.types import interrupt

from etl.db import get_connection, init_schema
from library.match import DuckDBMatchCache
from library.navidrome_playlist import (
    NavidromeNotConfigured,
    describe,
    list_navidrome_playlists_sync,
    save_to_navidrome,
)
from library.playback import playable
from library.playlists import list_playlists, to_jspf
from paths import DATA_DIR
from recommend.discover import discover
from sources.schemas import PlayableTrack, TrackRef
from utils.exceptions import SourceError
from utils.logging import get_logger

log = get_logger(__name__)

JSPF_DIR = DATA_DIR / "playlists"
_schema_ready = False
_read_only = False


def use_read_only_db() -> None:
    """Process-wide: ``db()`` opens read-only and cache writes are skipped.

    Called by the MCP server — the player API process is the DuckDB writer. Explicit
    writes (``db(write=True)``) still open read-write and fail on the lock.
    """
    global _read_only  # noqa: PLW0603
    _read_only = True


@contextmanager
def db(*, write: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    """Short-lived connection — another process (API, MCP, ETL) may want the file next."""
    global _schema_ready  # noqa: PLW0603
    read_only = _read_only and not write
    conn = get_connection(read_only=read_only)
    try:
        if not _schema_ready and not read_only:
            init_schema(conn)  # adds S4 tables to existing DBs
            _schema_ready = True
        yield conn
    finally:
        conn.close()


def match_cache() -> DuckDBMatchCache:
    """Navidrome match cache over the same short-lived connections as ``db()``."""
    read_only = _read_only

    def connect() -> duckdb.DuckDBPyConnection:
        return get_connection(read_only=read_only)

    return DuckDBMatchCache(connect, read_only=read_only)


def format_playable(p: PlayableTrack) -> str:
    lines = [f"{p.artist} — {p.title}"]
    if p.local_path:
        lines.append(f"Local file: {p.local_path}")
    lines.append(f"YouTube: {p.youtube_url}")
    if p.deezer_url:
        lines.append(f"Deezer: {p.deezer_url}")
    if p.preview_url:
        lines.append(f"30s preview: {p.preview_url}")
    return "\n".join(lines)


def _discover_tracks(
    artist: str, title: str | None = None, n: int = 15, new_artist_ratio: float = 0.5
) -> tuple[str, dict]:
    try:
        with db() as conn:
            cands = discover(artist, title, conn=conn, n=n, new_artist_ratio=new_artist_ratio)
    except duckdb.IOException as exc:
        log.warning("agent.tools.discover.no_history", error=str(exc))
        cands = discover(artist, title, n=n, new_artist_ratio=new_artist_ratio)
    if not cands:
        return f"No similar tracks found for {artist}.", {}
    lines = [
        f"{i}. {c.artist} — {c.title} ({'+'.join(c.sources)}"
        f"{', known artist' if c.known_artist else ', new artist'})"
        for i, c in enumerate(cands, 1)
    ]
    tracks = [TrackRef(artist=c.artist, title=c.title, mbid=c.mbid).model_dump() for c in cands]
    return "\n".join(lines), {"tracks": tracks}


discover_tracks_tool = StructuredTool.from_function(
    _discover_tracks,
    name="discover_tracks",
    description=(
        "Discover new tracks around a seed artist (and optionally a seed track title) "
        "using Last.fm, ListenBrainz and Deezer similarity, ranked against the user's "
        "listening history. new_artist_ratio (0–1) sets how many results come from "
        "artists the user hasn't played. Use for 'find me music like X'."
    ),
    response_format="content_and_artifact",
)


def resolve_track(artist: str, title: str) -> PlayableTrack:
    """Cached playback lookup; uncached if the DB is locked."""
    try:
        with db() as conn:
            return playable(artist, title, conn=conn)
    except duckdb.IOException:
        return playable(artist, title)


def _play_track(artist: str, title: str) -> tuple[str, dict]:
    p = resolve_track(artist, title)
    return format_playable(p), {"playable": [p.model_dump()]}


play_track_tool = StructuredTool.from_function(
    _play_track,
    name="play_track",
    description=(
        "Get free playback links for a track: full track on YouTube, plus a Deezer link "
        "and 30-second preview when available. Use when the user wants to listen to a song."
    ),
    response_format="content_and_artifact",
)


def write_jspf(name: str, tracks: list[TrackRef], description: str = "") -> Path:
    """JSPF export (importable into ListenBrainz and most players)."""
    JSPF_DIR.mkdir(parents=True, exist_ok=True)
    path = JSPF_DIR / f"{uuid.uuid4().hex[:12]}.jspf"
    path.write_text(json.dumps(to_jspf(name, tracks, description), indent=2))
    return path


async def save_playlist_to_library(
    name: str, tracks: list[TrackRef], description: str = ""
) -> tuple[str, list[TrackRef]]:
    """Navidrome playlist from the matched tracks + JSPF export; fails soft to JSPF only.

    Returns the tool text and the tracks that are not in the library.
    """
    jspf = await asyncio.to_thread(write_jspf, name, tracks, description)
    try:
        saved = await save_to_navidrome(name, tracks, cache=match_cache())
    except NavidromeNotConfigured:
        text = (
            f"Playlist '{name}' not saved to the music library: Navidrome isn't configured "
            f"(NAVIDROME_USER / NAVIDROME_PASSWORD). JSPF export: {jspf}"
        )
        return text, []
    except SourceError as exc:
        log.error("agent.tools.save_playlist.failed", error=str(exc))
        text = f"Failed to save playlist '{name}' to the music library: {exc}. JSPF export: {jspf}"
        return text, []
    return f"{describe(saved)}\nJSPF export: {jspf}", saved.unmatched


async def _save_playlist(
    name: str, tracks: list[TrackRef], description: str = ""
) -> tuple[str, dict]:
    confirmed = interrupt(
        {
            "type": "confirm_playlist_create",
            "name": name,
            "track_count": len(tracks),
            "description": description,
        }
    )
    if not confirmed:
        return f"Playlist '{name}' creation cancelled.", {}
    text, unmatched = await save_playlist_to_library(name, tracks, description)
    # unmatched tracks become the UI's track cards ("not in library" → preview / YouTube)
    return text, {"tracks": [t.model_dump() for t in unmatched]} if unmatched else {}


save_playlist_tool = StructuredTool.from_function(
    coroutine=_save_playlist,
    name="save_playlist",
    description=(
        "Save tracks (artist, title, optional MusicBrainz mbid) as a playlist in the user's "
        "music library (Navidrome), plus a JSPF export. Tracks not in the library are listed "
        "in the result — offer previews or free downloads for those. Call only when the user "
        "explicitly asks to save or create a playlist. Always interrupts to ask the user for "
        "confirmation first."
    ),
    response_format="content_and_artifact",
)


def _list_local_playlists() -> str:
    lines: list[str] = []
    library = list_navidrome_playlists_sync()
    if library:
        lines.append("Music library playlists:")
        lines += [f"- {p.name} ({p.song_count} tracks, id {p.id})" for p in library]
    try:
        with db() as conn:
            rows = list_playlists(conn)
            archived = conn.execute(
                "SELECT playlist_name FROM playlists WHERE status != 'excluded' ORDER BY 1"
            ).fetchall()
    except duckdb.IOException as exc:
        return "\n".join([*lines, f"Could not open the library database: {exc}"])
    if rows:
        lines.append("Older local playlists (JSPF-era):")
    elif not library:
        lines.append("No saved playlists yet.")
    lines += [
        f"- {r['name']} ({r['n_tracks']} tracks, id {r['id']}, {r['created_at']:%Y-%m-%d})"
        for r in rows
    ]
    if archived:
        lines.append("Archived Spotify playlists (usable with recommend_for_playlist):")
        lines += [f"- {name}" for (name,) in archived]
    return "\n".join(lines)


list_playlists_tool = StructuredTool.from_function(
    _list_local_playlists,
    name="get_user_playlists",
    description=(
        "List the user's playlists (music library + older local ones), plus archived Spotify-era playlists that "
        "recommend_for_playlist can use as seeds."
    ),
)
