from __future__ import annotations

import duckdb
from langchain_core.tools import StructuredTool

from paths import DATA_DIR, MODELS_DIR
from recommend.engine import RecommendationEngine
from recommend.schemas import RecommendRequest, RecommendResult
from utils.logging import get_logger

log = get_logger(__name__)

try:
    _engine: RecommendationEngine | None = RecommendationEngine(
        models_dir=MODELS_DIR,
        data_dir=DATA_DIR,
    )
except (FileNotFoundError, duckdb.IOException) as exc:
    _engine = None
    log.warning("agent.tools.engine_unavailable", error=str(exc))

_ENGINE_UNAVAILABLE = "Recommendation engine not available — models not trained. Run: make train"


def _format_result(result: RecommendResult) -> str:
    if not result.track_uris:
        return result.explanation
    lines = [result.explanation, ""]
    for i, (name, uri) in enumerate(zip(result.track_names, result.track_uris, strict=False), 1):
        lines.append(f"{i}. {name} [{uri}]")
    return "\n".join(lines)


def _recommend_similar_tracks(track_id: str, k: int = 10) -> str:
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
    if _engine is None:
        return _ENGINE_UNAVAILABLE
    result = _engine.recommend(RecommendRequest(request_type="artist", seed_id=artist_id, k=k))
    return _format_result(result)


recommend_for_artist = StructuredTool.from_function(
    _recommend_for_artist,
    name="recommend_for_artist",
    description="Find tracks matching an artist's sonic profile using their Spotify artist ID.",
)


def _recommend_by_genre(genre_name: str, k: int = 10) -> str:
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
    if _engine is None:
        return _ENGINE_UNAVAILABLE
    result = _engine.recommend(RecommendRequest(request_type="playlist", seed_id=playlist_id, k=k))
    return _format_result(result)


recommend_for_playlist = StructuredTool.from_function(
    _recommend_for_playlist,
    name="recommend_for_playlist",
    description="Find tracks to add to a Spotify playlist based on its audio fingerprint.",
)
