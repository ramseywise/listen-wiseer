"""Unit tests for agent tool wrappers.

All tests mock the engine and Spotify client — no pkl loads or Spotify auth.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from recommend.schemas import RecommendResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_result(
    n: int = 1,
    pipeline: str = "track",
    explanation: str = "Found tracks",
) -> RecommendResult:
    """Build a synthetic RecommendResult with n tracks."""
    return RecommendResult(
        track_uris=[f"spotify:track:id{i}" for i in range(n)],
        track_ids=[f"id{i}" for i in range(n)],
        track_names=[f"Track {i}" for i in range(n)],
        scores=[round(0.9 - i * 0.1, 2) for i in range(n)],
        pipeline_used=pipeline,
        explanation=explanation,
    )


EMPTY_RESULT = RecommendResult(
    track_uris=[],
    track_ids=[],
    track_names=[],
    scores=[],
    pipeline_used="track",
    explanation="Track not in corpus",
)


# ---------------------------------------------------------------------------
# _format_result
# ---------------------------------------------------------------------------


@patch("agent.tools._engine", MagicMock())
def test_format_result_with_tracks() -> None:
    from agent.tools import _format_result

    result = _make_result(n=2, explanation="Here are 2 tracks")
    formatted = _format_result(result)
    assert "Here are 2 tracks" in formatted
    assert "1. Track 0" in formatted
    assert "2. Track 1" in formatted
    assert "spotify:track:id0" in formatted


@patch("agent.tools._engine", MagicMock())
def test_format_result_empty() -> None:
    from agent.tools import _format_result

    formatted = _format_result(EMPTY_RESULT)
    assert formatted == "Track not in corpus"


# ---------------------------------------------------------------------------
# Recommend tools
# ---------------------------------------------------------------------------


@patch("agent.tools._engine")
def test_recommend_similar_tracks_returns_formatted(mock_engine: MagicMock) -> None:
    mock_engine.recommend.return_value = _make_result(n=3, explanation="Found 3")
    from agent.tools import _recommend_similar_tracks

    result = _recommend_similar_tracks("some_id", k=3)
    assert "Found 3" in result
    assert "Track 0" in result
    assert "Track 2" in result
    mock_engine.recommend.assert_called_once()


@patch("agent.tools._engine")
def test_recommend_similar_tracks_empty(mock_engine: MagicMock) -> None:
    mock_engine.recommend.return_value = EMPTY_RESULT
    from agent.tools import _recommend_similar_tracks

    result = _recommend_similar_tracks("nonexistent")
    assert result == "Track not in corpus"


@patch("agent.tools._engine", None)
def test_recommend_engine_unavailable() -> None:
    from agent.tools import _recommend_similar_tracks

    result = _recommend_similar_tracks("any_id")
    assert "not available" in result.lower() or "not trained" in result.lower()


@patch("agent.tools._engine")
def test_recommend_for_artist(mock_engine: MagicMock) -> None:
    mock_engine.recommend.return_value = _make_result(
        n=2, pipeline="artist", explanation="Artist matches"
    )
    from agent.tools import _recommend_for_artist

    result = _recommend_for_artist("artist_123", k=2)
    assert "Artist matches" in result


@patch("agent.tools._engine")
def test_recommend_by_genre(mock_engine: MagicMock) -> None:
    mock_engine.recommend.return_value = _make_result(
        n=5, pipeline="genre", explanation="Genre zone"
    )
    from agent.tools import _recommend_by_genre

    result = _recommend_by_genre("zouk", k=5)
    assert "Genre zone" in result
    assert "Track 4" in result


@patch("agent.tools._engine")
def test_recommend_for_playlist(mock_engine: MagicMock) -> None:
    mock_engine.recommend.return_value = _make_result(
        n=1, pipeline="playlist", explanation="Playlist fit"
    )
    from agent.tools import _recommend_for_playlist

    result = _recommend_for_playlist("playlist_abc", k=1)
    assert "Playlist fit" in result


# ---------------------------------------------------------------------------
# Spotify tools
# ---------------------------------------------------------------------------


@patch("agent.tools._engine", MagicMock())
@patch("agent.tools.fetch_recently_played")
@patch("agent.tools._get_client")
def test_get_recently_played_formats(
    mock_get_client: MagicMock,
    mock_fetch: MagicMock,
) -> None:
    from utils.schemas import TrackFeatures

    mock_fetch.return_value = [
        TrackFeatures(
            id="t1",
            uri="spotify:track:t1",
            name="Song A",
            release_date="2024-01-01",
            artist_ids=["a1"],
            artist_names=["Artist A"],
        ),
        TrackFeatures(
            id="t2",
            uri="spotify:track:t2",
            name="Song B",
            release_date="2024-02-01",
            artist_ids=["a2"],
            artist_names=["Artist B"],
        ),
    ]
    from agent.tools import _get_recently_played

    result = _get_recently_played(limit=2)
    assert "Song A" in result
    assert "Artist A" in result
    assert "Song B" in result
    assert "[t1]" in result


@patch("agent.tools._engine", MagicMock())
@patch("agent.tools.fetch_recently_played")
@patch("agent.tools._get_client")
def test_get_recently_played_empty(
    mock_get_client: MagicMock,
    mock_fetch: MagicMock,
) -> None:
    mock_fetch.return_value = []
    from agent.tools import _get_recently_played

    result = _get_recently_played()
    assert "No recently played" in result


@patch("agent.tools._engine", MagicMock())
@patch("agent.tools.fetch_recently_played", side_effect=Exception("Auth error"))
@patch("agent.tools._get_client")
def test_get_recently_played_error(
    mock_get_client: MagicMock,
    mock_fetch: MagicMock,
) -> None:
    from agent.tools import _get_recently_played

    result = _get_recently_played()
    assert "Failed to fetch" in result


@patch("agent.tools._engine", MagicMock())
@patch("agent.tools._get_client")
def test_search_tracks_formats(mock_get_client: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client.search.return_value = {
        "tracks": {
            "items": [
                {
                    "name": "Bossa Nova Baby",
                    "artists": [{"name": "Elvis Presley"}],
                    "id": "elvis123",
                },
            ],
        },
    }
    mock_get_client.return_value = mock_client
    from agent.tools import _search_tracks

    result = _search_tracks("bossa nova", limit=1)
    assert "Bossa Nova Baby" in result
    assert "Elvis Presley" in result
    assert "[elvis123]" in result


@patch("agent.tools._engine", MagicMock())
@patch("agent.tools._get_client")
def test_search_tracks_no_results(mock_get_client: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client.search.return_value = {"tracks": {"items": []}}
    mock_get_client.return_value = mock_client
    from agent.tools import _search_tracks

    result = _search_tracks("xyznonexistent")
    assert "No tracks found" in result


# ---------------------------------------------------------------------------
# ALL_TOOLS
# ---------------------------------------------------------------------------


@patch("agent.tools._engine", MagicMock())
def test_all_tools_count() -> None:
    from agent.tools import ALL_TOOLS

    assert len(ALL_TOOLS) == 6


@patch("agent.tools._engine", MagicMock())
def test_all_tools_names() -> None:
    from agent.tools import ALL_TOOLS

    names = {t.name for t in ALL_TOOLS}
    expected = {
        "recommend_similar_tracks",
        "recommend_for_artist",
        "recommend_by_genre",
        "recommend_for_playlist",
        "get_recently_played",
        "search_tracks",
    }
    assert names == expected
