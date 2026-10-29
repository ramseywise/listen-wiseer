from __future__ import annotations

from typing import Literal

import duckdb
from langchain_core.tools import StructuredTool

from agent.tools.discover import db
from etl.db import fetch_one
from paths import DATA_DIR, MODELS_DIR
from recommend.engine import RecommendationEngine
from recommend.schemas import RecommendRequest, RecommendResult
from utils.logging import get_logger

log = get_logger(__name__)

# Seeds are names; the corpus is keyed by the legacy Spotify IDs stored in DuckDB.


def _lookup(sql: str, params: list) -> str | None:
    with db() as conn:
        row = fetch_one(conn, sql, params)
    return row[0] if row else None


def _playlist_track_ids(playlist_id: str) -> list[str]:
    with db() as conn:
        rows = conn.execute(
            "SELECT track_id FROM playlist_tracks WHERE playlist_id = ? AND removed_at IS NULL",
            [playlist_id],
        ).fetchall()
    return [r[0] for r in rows]


try:
    _engine: RecommendationEngine | None = RecommendationEngine(
        models_dir=MODELS_DIR,
        data_dir=DATA_DIR,
        playlist_tracks_fn=_playlist_track_ids,
    )
except (FileNotFoundError, duckdb.IOException) as exc:
    _engine = None
    log.warning("agent.tools.engine_unavailable", error=str(exc))

_ENGINE_UNAVAILABLE = "Recommendation engine not available — models not trained. Run: make train"


def _format_result(result: RecommendResult) -> str:
    if not result.track_names:
        return result.explanation
    lines = [result.explanation, ""]
    lines += [f"{i}. {name}" for i, name in enumerate(result.track_names, 1)]
    return "\n".join(lines)


def _run(
    request_type: Literal["track", "artist", "playlist", "genre"],
    seed_id: str | None,
    missing: str,
    k: int,
) -> str:
    if _engine is None:
        return _ENGINE_UNAVAILABLE
    if seed_id is None:
        return missing
    result = _engine.recommend(RecommendRequest(request_type=request_type, seed_id=seed_id, k=k))
    return _format_result(result)


def _recommend_similar_tracks(artist: str, title: str, k: int = 10) -> str:
    track_id = _lookup(
        """
        SELECT t.track_id FROM tracks t
        JOIN track_artists USING (track_id) JOIN artists a USING (artist_id)
        WHERE lower(t.track_name) = lower(?) AND lower(a.artist_name) = lower(?)
        UNION ALL
        SELECT track_id FROM external_tracks
        WHERE lower(track_name) = lower(?) AND artist_names ILIKE '%' || ? || '%'
        LIMIT 1
        """,
        [title, artist, title, artist],
    )
    return _run("track", track_id, f"'{artist} — {title}' is not in the local corpus.", k)


recommend_similar_tracks = StructuredTool.from_function(
    _recommend_similar_tracks,
    name="recommend_similar_tracks",
    description=(
        "Find tracks with similar audio characteristics to a track in the local corpus "
        "(ENOA/GMM model). For tracks outside the corpus use discover_tracks."
    ),
)


def _recommend_for_artist(artist: str, k: int = 10) -> str:
    artist_id = _lookup(
        "SELECT artist_id FROM artists WHERE lower(artist_name) = lower(?) LIMIT 1", [artist]
    )
    return _run("artist", artist_id, f"Artist '{artist}' is not in the local corpus.", k)


recommend_for_artist = StructuredTool.from_function(
    _recommend_for_artist,
    name="recommend_for_artist",
    description="Find corpus tracks matching an artist's sonic profile (artist must be in the library).",
)


def _recommend_by_genre(genre_name: str, k: int = 10) -> str:
    return _run("genre", genre_name, "", k)


recommend_by_genre = StructuredTool.from_function(
    _recommend_by_genre,
    name="recommend_by_genre",
    description=(
        "Find tracks in a genre zone using the ENOA spatial map "
        "(e.g. 'zouk', 'bossa nova', 'house')."
    ),
)


def _recommend_for_playlist(playlist_name: str, k: int = 10) -> str:
    playlist_id = _lookup(
        """
        SELECT playlist_id FROM playlists WHERE playlist_name ILIKE '%' || ? || '%'
        ORDER BY lower(playlist_name) = lower(?) DESC, length(playlist_name) LIMIT 1
        """,
        [playlist_name, playlist_name],
    )
    return _run("playlist", playlist_id, f"No archived playlist matches '{playlist_name}'.", k)


recommend_for_playlist = StructuredTool.from_function(
    _recommend_for_playlist,
    name="recommend_for_playlist",
    description=(
        "Find tracks that fit an archived playlist's audio fingerprint, by playlist name "
        "(see get_user_playlists)."
    ),
)
