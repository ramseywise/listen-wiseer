"""StructuredTool wrappers for the LangGraph agent.

Wraps the same functions the MCP server uses as LangChain StructuredTool objects.
No MCP subprocess — direct Python calls. The agent's LLM sees these via bind_tools.

Memory tools (taste profile) use langmem with InjectedStore to access the shared
InMemoryStore compiled into the graph.
"""

from __future__ import annotations

import duckdb
from langchain_core.tools import StructuredTool
from langmem import create_manage_memory_tool, create_search_memory_tool

from paths import DATA_DIR, MODELS_DIR
from recommend.engine import RecommendationEngine
from recommend.schemas import RecommendRequest, RecommendResult
from spotify.client import SpotifyClient
from spotify.fetch import fetch_recently_played, fetch_related_artists
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
except (FileNotFoundError, duckdb.IOException) as exc:
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


def _get_related_artists(artist_id: str) -> str:
    """Find artists similar to a given Spotify artist ID."""
    from utils.exceptions import SpotifyClientError

    try:
        artists = fetch_related_artists(_get_client(), artist_id)
        if not artists:
            return f"No related artists found for {artist_id}"
        return "\n".join(
            f"- {a['name']} ({', '.join(a['genres']) or 'unknown genre'})"
            for a in artists
        )
    except SpotifyClientError as exc:
        log.warning("tool.get_related_artists.failed", error=str(exc))
        return f"Failed to fetch related artists: {exc}"


get_related_artists_tool = StructuredTool.from_function(
    _get_related_artists,
    name="get_related_artists",
    description=(
        "Find artists that sound similar to a given Spotify artist ID. "
        "Use for 'who sounds like X?' or 'artists similar to X' queries. "
        "Requires a Spotify artist ID — use search_tracks first to find the ID."
    ),
)

# ---------------------------------------------------------------------------
# RAG knowledge tool — lazy singleton (avoids SentenceTransformer load at import)
# ---------------------------------------------------------------------------
_music_rag = None


def _get_music_rag():
    """Return a lazily-initialized MusicRAG singleton."""
    global _music_rag  # noqa: PLW0603
    if _music_rag is None:
        from rag_core.orchestration.music_rag import MusicRAG

        _music_rag = MusicRAG()
    return _music_rag


def _get_artist_context(subject: str) -> str:
    """Retrieve biographical info and interesting facts about a musician, band, or genre."""
    return _get_music_rag().get_context(subject)


get_artist_context_tool = StructuredTool.from_function(
    _get_artist_context,
    name="get_artist_context",
    description=(
        "Retrieve biographical info and interesting facts about a musician or band. "
        "Use when the user asks who an artist is, what they're known for, "
        "their history, influences, or style. Also works for music genres."
    ),
)

# ---------------------------------------------------------------------------
# Taste memory tools — backed by langmem + InjectedStore
#
# Namespace uses {langgraph_user_id} template — LangGraph resolves it from
# config["configurable"] at runtime, scoping memories per user.
# ---------------------------------------------------------------------------

_TASTE_NAMESPACE = ("enoa", "{langgraph_user_id}", "taste")

manage_taste_memory = create_manage_memory_tool(
    _TASTE_NAMESPACE,
    name="manage_taste_memory",
    instructions=(
        "Proactively call this tool when you identify a user's musical taste preference, "
        "genre affinity, or explicit request to remember something about their listening habits. "
        "Examples: 'prefers acoustic over electronic', 'loves zouk', 'dislikes BPM > 140'."
    ),
)

search_taste_memory = create_search_memory_tool(
    _TASTE_NAMESPACE,
    name="search_taste_memory",
    instructions=(
        "Search stored facts about the user's musical taste. "
        "Use this to recall user preferences before making recommendations."
    ),
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
    get_related_artists_tool,
    get_artist_context_tool,
    manage_taste_memory,
    search_taste_memory,
]
