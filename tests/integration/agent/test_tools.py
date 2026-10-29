"""Agent tool wrappers against a mocked engine — no pkl loads, no network.

Name → corpus-ID lookup SQL is covered in tests/unit/agent/test_recommend_tools.py;
here `_lookup` is patched so only formatting and engine routing are exercised.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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


@patch("agent.tools.recommend._engine", MagicMock())
def test_format_result_with_tracks() -> None:
    from agent.tools.recommend import _format_result

    result = _make_result(n=2, explanation="Here are 2 tracks")
    formatted = _format_result(result)
    assert "Here are 2 tracks" in formatted
    assert "1. Track 0" in formatted
    assert "2. Track 1" in formatted
    assert "spotify:" not in formatted


@patch("agent.tools.recommend._engine", MagicMock())
def test_format_result_empty() -> None:
    from agent.tools.recommend import _format_result

    formatted = _format_result(EMPTY_RESULT)
    assert formatted == "Track not in corpus"


# ---------------------------------------------------------------------------
# Recommend tools
# ---------------------------------------------------------------------------


@patch("agent.tools.recommend._lookup", return_value="some_id")
@patch("agent.tools.recommend._engine")
def test_recommend_similar_tracks_returns_formatted(
    mock_engine: MagicMock, _lookup: MagicMock
) -> None:
    mock_engine.recommend.return_value = _make_result(n=3, explanation="Found 3")
    from agent.tools.recommend import _recommend_similar_tracks

    result = _recommend_similar_tracks("Radiohead", "Reckoner", k=3)
    assert "Found 3" in result
    assert "Track 0" in result
    assert "Track 2" in result
    mock_engine.recommend.assert_called_once()


@patch("agent.tools.recommend._lookup", return_value="some_id")
@patch("agent.tools.recommend._engine")
def test_recommend_similar_tracks_empty(mock_engine: MagicMock, _lookup: MagicMock) -> None:
    mock_engine.recommend.return_value = EMPTY_RESULT
    from agent.tools.recommend import _recommend_similar_tracks

    result = _recommend_similar_tracks("Nobody", "nothing")
    assert result == "Track not in corpus"


@patch("agent.tools.recommend._engine", None)
def test_recommend_engine_unavailable() -> None:
    from agent.tools.recommend import _recommend_by_genre

    result = _recommend_by_genre("zouk")
    assert "not available" in result.lower() or "not trained" in result.lower()


@patch("agent.tools.recommend._lookup", return_value="artist_123")
@patch("agent.tools.recommend._engine")
def test_recommend_for_artist(mock_engine: MagicMock, _lookup: MagicMock) -> None:
    mock_engine.recommend.return_value = _make_result(
        n=2, pipeline="artist", explanation="Artist matches"
    )
    from agent.tools.recommend import _recommend_for_artist

    result = _recommend_for_artist("Radiohead", k=2)
    assert "Artist matches" in result


@patch("agent.tools.recommend._engine")
def test_recommend_by_genre(mock_engine: MagicMock) -> None:
    mock_engine.recommend.return_value = _make_result(
        n=5, pipeline="genre", explanation="Genre zone"
    )
    from agent.tools.recommend import _recommend_by_genre

    result = _recommend_by_genre("zouk", k=5)
    assert "Genre zone" in result
    assert "Track 4" in result


@patch("agent.tools.recommend._lookup", return_value="playlist_abc")
@patch("agent.tools.recommend._engine")
def test_recommend_for_playlist(mock_engine: MagicMock, _lookup: MagicMock) -> None:
    mock_engine.recommend.return_value = _make_result(
        n=1, pipeline="playlist", explanation="Playlist fit"
    )
    from agent.tools.recommend import _recommend_for_playlist

    result = _recommend_for_playlist("zouk", k=1)
    assert "Playlist fit" in result


# ---------------------------------------------------------------------------
# ALL_TOOLS
# ---------------------------------------------------------------------------


@patch("agent.tools.recommend._engine", MagicMock())
def test_all_tools_count() -> None:
    from agent.tools import ALL_TOOLS

    assert len(ALL_TOOLS) == 21


@patch("agent.tools.recommend._engine", MagicMock())
def test_all_tools_names() -> None:
    from agent.tools import ALL_TOOLS

    names = {t.name for t in ALL_TOOLS}
    expected = {
        "discover_tracks",
        "play_track",
        "save_playlist",
        "get_user_playlists",
        "recommend_similar_tracks",
        "recommend_for_artist",
        "recommend_by_genre",
        "recommend_for_playlist",
        "get_top_tracks",
        "get_top_artists",
        "get_recently_played",
        "get_taste_analysis",
        "search_tracks",
        "get_artist_info",
        "get_related_artists",
        "get_artist_top_tracks",
        "get_artist_albums",
        "get_artist_context",
        "get_genre_context",
        "manage_taste_memory",
        "search_taste_memory",
    }
    assert names == expected
