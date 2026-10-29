"""Spotify-free discovery, playback and local playlists.

Tools return content + artifact: the artifact carries structured tracks so
format_response can hand them to the UI (play buttons, save-as-playlist).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import duckdb
from langchain_core.tools import StructuredTool
from langgraph.types import interrupt

from etl.db import get_connection, init_schema
from library.playback import playable
from library.playlists import list_playlists, save_playlist, to_jspf
from paths import DATA_DIR
from recommend.discover import discover
from sources.schemas import PlayableTrack, TrackRef
from utils.logging import get_logger

log = get_logger(__name__)

JSPF_DIR = DATA_DIR / "playlists"
_schema_ready = False


@contextmanager
def db() -> Iterator[duckdb.DuckDBPyConnection]:
    """Short-lived connection — the MCP server / ETL may hold the file between calls."""
    global _schema_ready  # noqa: PLW0603
    conn = get_connection()
    try:
        if not _schema_ready:
            init_schema(conn)  # adds S4 tables to existing DBs
            _schema_ready = True
        yield conn
    finally:
        conn.close()


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


def _save_local_playlist(name: str, tracks: list[TrackRef], description: str = "") -> str:
    confirmed = interrupt(
        {
            "type": "confirm_playlist_create",
            "name": name,
            "track_count": len(tracks),
            "description": description,
        }
    )
    if not confirmed:
        return f"Playlist '{name}' creation cancelled."
    try:
        with db() as conn:
            pid = save_playlist(conn, name, tracks, description)
    except duckdb.IOException as exc:
        log.error("agent.tools.save_playlist.failed", error=str(exc))
        return f"Failed to save playlist: {exc}"
    JSPF_DIR.mkdir(parents=True, exist_ok=True)
    path = JSPF_DIR / f"{pid}.jspf"
    path.write_text(json.dumps(to_jspf(name, tracks, description), indent=2))
    return (
        f"Saved playlist '{name}' with {len(tracks)} tracks (id {pid}). "
        f"JSPF export: {path} — importable into ListenBrainz."
    )


save_playlist_tool = StructuredTool.from_function(
    _save_local_playlist,
    name="save_playlist",
    description=(
        "Save tracks (artist, title, optional MusicBrainz mbid) as a local playlist and "
        "export it as JSPF. Call only when the user explicitly asks to save or create a "
        "playlist. Always interrupts to ask the user for confirmation first."
    ),
)


def _list_local_playlists() -> str:
    try:
        with db() as conn:
            rows = list_playlists(conn)
            archived = conn.execute(
                "SELECT playlist_name FROM playlists WHERE status != 'excluded' ORDER BY 1"
            ).fetchall()
    except duckdb.IOException as exc:
        return f"Could not open the library database: {exc}"
    lines = ["Saved playlists:"] if rows else ["No saved playlists yet."]
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
        "List the user's saved playlists, plus archived Spotify-era playlists that "
        "recommend_for_playlist can use as seeds."
    ),
)
