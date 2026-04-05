"""Tests for recommendation MCP tools in mcp_server/server.py."""

from unittest.mock import MagicMock, patch

import pytest

from recommend.schemas import RecommendResult


def _make_result(track_ids=("abc123", "def456"), explanation="Found 2 tracks."):
    return RecommendResult(
        track_uris=[f"spotify:track:{t}" for t in track_ids],
        track_ids=list(track_ids),
        track_names=[f"Track {t}" for t in track_ids],
        scores=[0.9, 0.8],
        pipeline_used="track",
        explanation=explanation,
    )


def _empty_result(explanation="No tracks found."):
    return RecommendResult(
        track_uris=[],
        track_ids=[],
        track_names=[],
        scores=[],
        pipeline_used="track",
        explanation=explanation,
    )


@pytest.fixture()
def mock_engine():
    engine = MagicMock()
    engine.recommend.return_value = _make_result()
    return engine


class TestRecommendSimilarTracks:
    def test_returns_non_empty_string(self, mock_engine):
        with patch("mcp_server.server._engine", mock_engine):
            from mcp_server.server import recommend_similar_tracks

            result = recommend_similar_tracks("4bJ7tMJqfYmkKgCYzaaG4B", k=5)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_track_uris_in_output(self, mock_engine):
        with patch("mcp_server.server._engine", mock_engine):
            from mcp_server.server import recommend_similar_tracks

            result = recommend_similar_tracks("4bJ7tMJqfYmkKgCYzaaG4B")
        assert "spotify:track:abc123" in result

    def test_empty_result_returns_explanation(self, mock_engine):
        mock_engine.recommend.return_value = _empty_result("Track not in corpus.")
        with patch("mcp_server.server._engine", mock_engine):
            from mcp_server.server import recommend_similar_tracks

            result = recommend_similar_tracks("UNKNOWN_ID")
        assert result == "Track not in corpus."

    def test_engine_none_returns_not_trained_message(self):
        with patch("mcp_server.server._engine", None):
            from mcp_server.server import recommend_similar_tracks

            result = recommend_similar_tracks("any_id")
        assert "make train" in result.lower() or "not trained" in result.lower()


class TestRecommendForArtist:
    def test_returns_non_empty_string(self, mock_engine):
        mock_engine.recommend.return_value = _make_result(explanation="Artist match.")
        with patch("mcp_server.server._engine", mock_engine):
            from mcp_server.server import recommend_for_artist

            result = recommend_for_artist("artist_id_123")
        assert isinstance(result, str) and len(result) > 0

    def test_engine_none_returns_not_trained_message(self):
        with patch("mcp_server.server._engine", None):
            from mcp_server.server import recommend_for_artist

            result = recommend_for_artist("any_artist")
        assert "make train" in result.lower() or "not trained" in result.lower()


class TestRecommendForPlaylist:
    def test_returns_non_empty_string(self, mock_engine):
        mock_engine.recommend.return_value = _make_result(explanation="Playlist match.")
        with patch("mcp_server.server._engine", mock_engine):
            from mcp_server.server import recommend_for_playlist

            result = recommend_for_playlist("playlist_id_123")
        assert isinstance(result, str) and len(result) > 0

    def test_engine_none_returns_not_trained_message(self):
        with patch("mcp_server.server._engine", None):
            from mcp_server.server import recommend_for_playlist

            result = recommend_for_playlist("any_playlist")
        assert "make train" in result.lower() or "not trained" in result.lower()


class TestRecommendByGenre:
    def test_returns_non_empty_string(self, mock_engine):
        mock_engine.recommend.return_value = _make_result(explanation="Genre zone results.")
        with patch("mcp_server.server._engine", mock_engine):
            from mcp_server.server import recommend_by_genre

            result = recommend_by_genre("zouk")
        assert isinstance(result, str) and len(result) > 0

    def test_unknown_genre_returns_explanation(self, mock_engine):
        mock_engine.recommend.return_value = _empty_result("Genre 'xyz_fake' not found.")
        with patch("mcp_server.server._engine", mock_engine):
            from mcp_server.server import recommend_by_genre

            result = recommend_by_genre("xyz_fake")
        assert "not found" in result.lower()

    def test_engine_none_returns_not_trained_message(self):
        with patch("mcp_server.server._engine", None):
            from mcp_server.server import recommend_by_genre

            result = recommend_by_genre("zouk")
        assert "make train" in result.lower() or "not trained" in result.lower()
