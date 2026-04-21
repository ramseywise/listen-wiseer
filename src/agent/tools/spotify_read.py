from __future__ import annotations

from langchain_core.tools import StructuredTool

from spotify.client import SpotifyClient
from spotify.fetch import fetch_recently_played, fetch_related_artists
from utils.logging import get_logger

log = get_logger(__name__)

_client: SpotifyClient | None = None


def _get_client() -> SpotifyClient:
    global _client  # noqa: PLW0603
    if _client is None:
        _client = SpotifyClient()
    return _client


def _get_recently_played(limit: int = 20) -> str:
    try:
        tracks = fetch_recently_played(_get_client(), limit=limit)
        if not tracks:
            return "No recently played tracks found."
        return "\n".join(
            f"{i}. {t.name} — {', '.join(t.artist_names)} [{t.id}]"
            for i, t in enumerate(tracks, 1)
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
