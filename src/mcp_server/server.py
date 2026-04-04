"""
MCP server exposing Spotify READ operations as tools for LLM agents.
Run with: uv run python src/mcp_server/server.py
"""

from mcp.server.fastmcp import FastMCP

from paths import DATA_DIR, MODELS_DIR
from recommend.engine import RecommendationEngine
from recommend.schemas import RecommendRequest
from spotify.client import SpotifyClient
from spotify.fetch import (
    fetch_audio_features,
    fetch_playlist_tracks,
    fetch_recently_played,
)
from utils.logging import get_logger

log = get_logger(__name__)

mcp = FastMCP("listen-wiseer")

try:
    _engine: RecommendationEngine | None = RecommendationEngine(
        models_dir=MODELS_DIR,
        data_dir=DATA_DIR,
    )
except FileNotFoundError as exc:
    _engine = None
    log.warning("mcp.engine.unavailable", error=str(exc))


@mcp.tool()
def get_playlist_tracks(playlist_id: str) -> str:
    """Get the list of tracks in a Spotify playlist by playlist ID."""
    sp = SpotifyClient()
    tracks = fetch_playlist_tracks(sp, playlist_id)
    return "\n".join(f"{t.name} — {', '.join(t.artist_names)}" for t in tracks)


@mcp.tool()
def get_track_features(track_id: str) -> str:
    """Get audio features for a Spotify track by track ID."""
    sp = SpotifyClient()
    features = fetch_audio_features(sp, [track_id])
    return str(features[0].model_dump()) if features else f"No features found for {track_id}"


@mcp.tool()
def get_recently_played(limit: int = 20) -> str:
    """Get the current user's recently played tracks."""
    sp = SpotifyClient()
    tracks = fetch_recently_played(sp, limit=limit)
    return "\n".join(f"{t.name} — {', '.join(t.artist_names)}" for t in tracks)


@mcp.tool()
def search_tracks(query: str, limit: int = 10) -> str:
    """Search Spotify for tracks matching a query."""
    from utils.exceptions import SpotifyClientError

    sp = SpotifyClient()
    try:
        results = sp.search(q=query, type="track", limit=limit)
        items = results["tracks"]["items"]
    except (SpotifyClientError, KeyError) as e:
        return f"Search failed: {e}"
    return "\n".join(
        f"{t['name']} — {', '.join(a['name'] for a in t['artists'])} [{t['id']}]" for t in items
    )


def _format_result(result) -> str:
    if not result.track_uris:
        return result.explanation
    lines = [result.explanation, ""]
    for i, (name, uri) in enumerate(zip(result.track_names, result.track_uris, strict=False), 1):
        lines.append(f"{i}. {name} [{uri}]")
    return "\n".join(lines)


@mcp.tool()
def recommend_similar_tracks(track_id: str, k: int = 10) -> str:
    """Find tracks with similar audio characteristics to a given Spotify track ID."""
    if _engine is None:
        return "Recommendation models not trained yet. Run: make train"
    result = _engine.recommend(RecommendRequest(request_type="track", seed_id=track_id, k=k))
    return _format_result(result)


@mcp.tool()
def recommend_for_artist(artist_id: str, k: int = 10) -> str:
    """Find tracks matching an artist's sonic profile using their Spotify artist ID."""
    if _engine is None:
        return "Recommendation models not trained yet. Run: make train"
    result = _engine.recommend(RecommendRequest(request_type="artist", seed_id=artist_id, k=k))
    return _format_result(result)


@mcp.tool()
def recommend_for_playlist(playlist_id: str, k: int = 10) -> str:
    """Find tracks to add to a Spotify playlist based on its audio fingerprint."""
    if _engine is None:
        return "Recommendation models not trained yet. Run: make train"
    result = _engine.recommend(RecommendRequest(request_type="playlist", seed_id=playlist_id, k=k))
    return _format_result(result)


@mcp.tool()
def recommend_by_genre(genre_name: str, k: int = 10) -> str:
    """Find tracks in a genre zone using ENOA spatial map (e.g. 'zouk', 'bossa nova', 'house')."""
    if _engine is None:
        return "Recommendation models not trained yet. Run: make train"
    result = _engine.recommend(RecommendRequest(request_type="genre", seed_id=genre_name, k=k))
    return _format_result(result)


if __name__ == "__main__":
    mcp.run()
