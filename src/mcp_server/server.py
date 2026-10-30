"""
MCP server exposing the agent's music tools to other LLM clients (e.g. Claude Code).
Run with: uv run python src/mcp_server/server.py
Transport via MCP_TRANSPORT: "stdio" (default, Claude Code / .mcp.json) or
"streamable-http" (binds MCP_SERVER_HOST:MCP_SERVER_PORT, endpoint /mcp — used by Docker).

Tools are the agent's own StructuredTools, so behaviour stays in parity. Exceptions:
memory tools need the LangGraph store (agent only), and save_playlist skips the HITL
interrupt — MCP clients confirm tool calls themselves. save_playlist writes to Navidrome with
its own short-lived Subsonic client from settings (this process is not the API).

DuckDB is single-writer across processes and the player API is the writer: this server opens
it read-only (cache writes skipped); download_track's one write fails clearly when locked.
"""

# ruff: noqa: E402
import sys

import structlog

if __name__ == "__main__":
    # stdout is the protocol channel under stdio; tool modules log at import time, so
    # route structlog to stderr before importing them. Skipped when imported (tests).
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))

import inspect
from collections.abc import Callable
from functools import wraps

from langchain_core.tools import StructuredTool
from mcp.server.fastmcp import FastMCP

from agent.tools import (
    discover_tracks_tool,
    download_track_tool,
    find_free_downloads_tool,
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
from agent.tools.discover import save_playlist_to_library, use_read_only_db
from sources.schemas import TrackRef
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

mcp = FastMCP("listen-wiseer", host=settings.mcp_server_host, port=settings.mcp_server_port)

_EXPOSED: list[StructuredTool] = [
    discover_tracks_tool,
    play_track_tool,
    find_free_downloads_tool,
    download_track_tool,
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
async def save_playlist(name: str, tracks: list[TrackRef], description: str = "") -> str:
    """Save tracks (artist, title, optional MusicBrainz mbid) as a playlist in the music
    library (Navidrome) plus a JSPF export. Tracks not in the library are listed in the result."""
    text, _unmatched = await save_playlist_to_library(name, tracks, description)
    return text


def main() -> None:
    use_read_only_db()
    log.info(
        "mcp_server.start",
        transport=settings.mcp_transport,
        host=settings.mcp_server_host,
        port=settings.mcp_server_port,
        db_read_only=True,
    )
    mcp.run(transport=settings.mcp_transport)


if __name__ == "__main__":
    main()
