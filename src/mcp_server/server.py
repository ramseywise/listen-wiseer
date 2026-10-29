"""
MCP server exposing the agent's music tools to other LLM clients (e.g. Claude Code).
Run with: uv run python src/mcp_server/server.py

Tools are the agent's own StructuredTools, so behaviour stays in parity. Exceptions:
memory tools need the LangGraph store (agent only), and save_playlist skips the HITL
interrupt — MCP clients confirm tool calls themselves.
"""

import inspect
import json
from collections.abc import Callable
from functools import wraps

import duckdb
from langchain_core.tools import StructuredTool
from mcp.server.fastmcp import FastMCP

from agent.tools import (
    discover_tracks_tool,
    get_artist_albums_tool,
    get_artist_context_tool,
    get_artist_info_tool,
    get_artist_top_tracks_tool,
    get_genre_context_tool,
    get_recently_played_tool,
    get_related_artists_tool,
    get_taste_analysis_tool,
    get_top_artists_tool,
    get_top_tracks_tool,
    list_playlists_tool,
    play_track_tool,
    recommend_by_genre,
    recommend_for_artist,
    recommend_for_playlist,
    recommend_similar_tracks,
    search_tracks_tool,
)
from agent.tools.discover import JSPF_DIR, db
from library.playlists import save_playlist as save_playlist_db
from library.playlists import to_jspf
from sources.schemas import TrackRef
from utils.logging import get_logger

log = get_logger(__name__)

mcp = FastMCP("listen-wiseer")

_EXPOSED: list[StructuredTool] = [
    discover_tracks_tool,
    play_track_tool,
    recommend_similar_tracks,
    recommend_for_artist,
    recommend_by_genre,
    recommend_for_playlist,
    get_top_tracks_tool,
    get_top_artists_tool,
    get_recently_played_tool,
    get_taste_analysis_tool,
    search_tracks_tool,
    get_artist_info_tool,
    get_related_artists_tool,
    get_artist_top_tracks_tool,
    get_artist_albums_tool,
    get_artist_context_tool,
    get_genre_context_tool,
    list_playlists_tool,
]


def _content_only(fn: Callable) -> Callable:
    """Drop the artifact from content_and_artifact tools — MCP returns text."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)[0]

    wrapper.__signature__ = inspect.signature(fn).replace(return_annotation=str)  # type: ignore[attr-defined]
    return wrapper


for _tool in _EXPOSED:
    if _tool.func is None:
        continue
    _fn = (
        _content_only(_tool.func) if _tool.response_format == "content_and_artifact" else _tool.func
    )
    mcp.add_tool(_fn, name=_tool.name, description=_tool.description)


@mcp.tool()
def save_playlist(name: str, tracks: list[TrackRef], description: str = "") -> str:
    """Save tracks (artist, title, optional MusicBrainz mbid) as a local playlist and
    export it as JSPF (importable into ListenBrainz)."""
    try:
        with db() as conn:
            pid = save_playlist_db(conn, name, tracks, description)
    except duckdb.IOException as exc:
        return f"Failed to save playlist: {exc}"
    JSPF_DIR.mkdir(parents=True, exist_ok=True)
    path = JSPF_DIR / f"{pid}.jspf"
    path.write_text(json.dumps(to_jspf(name, tracks, description), indent=2))
    return f"Saved playlist '{name}' with {len(tracks)} tracks (id {pid}). JSPF export: {path}"


if __name__ == "__main__":
    mcp.run()
