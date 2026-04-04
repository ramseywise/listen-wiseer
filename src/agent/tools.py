"""StructuredTool wrappers for the LangGraph agent.

Wraps the same functions the MCP server uses as LangChain StructuredTool objects.
No MCP subprocess — direct Python calls. The agent's LLM sees these via bind_tools.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool

from paths import DATA_DIR, MODELS_DIR
from recommend.engine import RecommendationEngine
from recommend.schemas import RecommendRequest, RecommendResult
from spotify.client import SpotifyClient
from spotify.fetch import fetch_recently_played
from utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Engine — eagerly loaded, fail-soft (same pattern as mcp_server/server.py)
# ---------------------------------------------------------------------------
try:
    _engine: RecommendationEngine | None = RecommendationEngine(
        models_dir=MODELS_DIR,
        data_dir=DATA_DIR,
    )
except FileNotFoundError as exc:
    _engine = None
    log.warning("agent.tools.engine_unavailable", error=str(exc))

_ENGINE_UNAVAILABLE = "Recommendation engine not available — models not trained. Run: make train"

# ---------------------------------------------------------------------------
# Spotify client — lazy singleton, created on first Spotify tool call
# ---------------------------------------------------------------------------
_client: SpotifyClient | None = None


def _get_client() -> SpotifyClient:
    """Return a lazily-initialized SpotifyClient singleton."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = SpotifyClient()
    return _client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_result(result: RecommendResult) -> str:
    """Format a RecommendResult into a human-readable string."""
    if not result.track_uris:
        return result.explanation
    lines = [result.explanation, ""]
    for i, (name, uri) in enumerate(zip(result.track_names, result.track_uris, strict=False), 1):
        lines.append(f"{i}. {name} [{uri}]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Recommend tools
# ---------------------------------------------------------------------------


def _recommend_similar_tracks(track_id: str, k: int = 10) -> str:
    """Find corpus tracks similar to a given Spotify track ID."""
    if _engine is None:
        return _ENGINE_UNAVAILABLE
    result = _engine.recommend(RecommendRequest(request_type="track", seed_id=track_id, k=k))
    return _format_result(result)


recommend_similar_tracks = StructuredTool.from_function(
    _recommend_similar_tracks,
    name="recommend_similar_tracks",
    description="Find tracks with similar audio characteristics to a Spotify track ID.",
)


def _recommend_for_artist(artist_id: str, k: int = 10) -> str:
    """Find tracks matching an artist's sonic profile using their Spotify artist ID."""
    if _engine is None:
        return _ENGINE_UNAVAILABLE
    result = _engine.recommend(RecommendRequest(request_type="artist", seed_id=artist_id, k=k))
    return _format_result(result)


recommend_for_artist = StructuredTool.from_function(
    _recommend_for_artist,
    name="recommend_for_artist",
    description=("Find tracks matching an artist's sonic profile using their Spotify artist ID."),
)


def _recommend_by_genre(genre_name: str, k: int = 10) -> str:
    """Find tracks in a genre zone using the ENOA spatial map (e.g. 'zouk', 'bossa nova', 'house')."""
    if _engine is None:
        return _ENGINE_UNAVAILABLE
    result = _engine.recommend(RecommendRequest(request_type="genre", seed_id=genre_name, k=k))
    return _format_result(result)


recommend_by_genre = StructuredTool.from_function(
    _recommend_by_genre,
    name="recommend_by_genre",
    description=(
        "Find tracks in a genre zone using the ENOA spatial map "
        "(e.g. 'zouk', 'bossa nova', 'house')."
    ),
)


def _recommend_for_playlist(playlist_id: str, k: int = 10) -> str:
    """Find tracks to add to a Spotify playlist based on its audio fingerprint."""
    if _engine is None:
        return _ENGINE_UNAVAILABLE
    result = _engine.recommend(RecommendRequest(request_type="playlist", seed_id=playlist_id, k=k))
    return _format_result(result)


recommend_for_playlist = StructuredTool.from_function(
    _recommend_for_playlist,
    name="recommend_for_playlist",
    description=("Find tracks to add to a Spotify playlist based on its audio fingerprint."),
)

# ---------------------------------------------------------------------------
# Spotify fetch tools
# ---------------------------------------------------------------------------


def _get_recently_played(limit: int = 20) -> str:
    """Get the user's recently played tracks from Spotify."""
    try:
        tracks = fetch_recently_played(_get_client(), limit=limit)
        if not tracks:
            return "No recently played tracks found."
        return "\n".join(
            f"{i}. {t.name} — {', '.join(t.artist_names)} [{t.id}]" for i, t in enumerate(tracks, 1)
        )
    except Exception as exc:
        log.error("agent.tools.recently_played.failed", error=str(exc))
        return f"Failed to fetch recently played: {exc}"


get_recently_played_tool = StructuredTool.from_function(
    _get_recently_played,
    name="get_recently_played",
    description="Get the user's recently played tracks from Spotify.",
)


def _search_tracks(query: str, limit: int = 10) -> str:
    """Search Spotify for tracks matching a text query."""
    from utils.exceptions import SpotifyClientError

    try:
        results = _get_client().search(q=query, type="track", limit=limit)
        items = results["tracks"]["items"]
    except (SpotifyClientError, KeyError) as exc:
        log.error("agent.tools.search.failed", error=str(exc))
        return f"Search failed: {exc}"
    if not items:
        return f"No tracks found for '{query}'."
    return "\n".join(
        f"{i}. {t['name']} — {', '.join(a['name'] for a in t['artists'])} [{t['id']}]"
        for i, t in enumerate(items, 1)
    )


search_tracks_tool = StructuredTool.from_function(
    _search_tracks,
    name="search_tracks",
    description="Search Spotify for tracks matching a text query.",
)

# ---------------------------------------------------------------------------
# Collected tool list — imported by nodes.py and graph.py
# ---------------------------------------------------------------------------

ALL_TOOLS: list[StructuredTool] = [
    recommend_similar_tracks,
    recommend_for_artist,
    recommend_by_genre,
    recommend_for_playlist,
    get_recently_played_tool,
    search_tracks_tool,
]
