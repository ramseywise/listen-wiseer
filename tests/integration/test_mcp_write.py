"""Tests for write and playback MCP tools in mcp_server/server.py."""

from unittest.mock import MagicMock, patch

import pytest

from utils.exceptions import SpotifyAuthError

pytestmark = pytest.mark.integration


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.post.return_value = {"id": "pl_test_123"}
    client.put.return_value = {}
    client.get.return_value = {
        "is_playing": True,
        "progress_ms": 60000,
        "item": {
            "name": "Test Track",
            "duration_ms": 200000,
            "artists": [{"name": "Test Artist"}],
            "album": {"name": "Test Album"},
        },
        "device": {"name": "MacBook", "type": "Computer"},
    }
    return client


class TestCreatePlaylist:
    def test_success_returns_url(self, mock_client):
        with patch("mcp_server.server.SpotifyClient", return_value=mock_client):
            from mcp_server.server import create_playlist

            result = create_playlist("My Mix", description="chill vibes")
        assert "pl_test_123" in result
        assert "https://open.spotify.com/playlist/" in result

    def test_auth_error_returns_message(self):
        with patch("mcp_server.server.SpotifyClient", side_effect=SpotifyAuthError("expired")):
            from mcp_server.server import create_playlist

            result = create_playlist("Test")
        assert "make auth" in result


class TestAddTracksToPlaylist:
    def test_success_reports_count(self, mock_client):
        with patch("mcp_server.server.SpotifyClient", return_value=mock_client):
            from mcp_server.server import add_tracks_to_playlist

            result = add_tracks_to_playlist("pl_123", ["track1", "track2", "track3"])
        assert "3 tracks" in result

    def test_empty_track_list(self, mock_client):
        with patch("mcp_server.server.SpotifyClient", return_value=mock_client):
            from mcp_server.server import add_tracks_to_playlist

            result = add_tracks_to_playlist("pl_123", [])
        assert "No track IDs" in result

    def test_auth_error_returns_message(self):
        with patch("mcp_server.server.SpotifyClient", side_effect=SpotifyAuthError("expired")):
            from mcp_server.server import add_tracks_to_playlist

            result = add_tracks_to_playlist("pl_123", ["track1"])
        assert "make auth" in result


class TestCreatePlaylistWithTracks:
    def test_success_returns_url_and_count(self, mock_client):
        with patch("mcp_server.server.SpotifyClient", return_value=mock_client):
            from mcp_server.server import create_playlist_with_tracks

            result = create_playlist_with_tracks("Party", ["t1", "t2"])
        assert "pl_test_123" in result
        assert "2 tracks" in result

    def test_empty_track_list(self, mock_client):
        with patch("mcp_server.server.SpotifyClient", return_value=mock_client):
            from mcp_server.server import create_playlist_with_tracks

            result = create_playlist_with_tracks("Empty", [])
        assert "No track IDs" in result

    def test_auth_error_returns_message(self):
        with patch("mcp_server.server.SpotifyClient", side_effect=SpotifyAuthError("expired")):
            from mcp_server.server import create_playlist_with_tracks

            result = create_playlist_with_tracks("Test", ["t1"])
        assert "make auth" in result


class TestPlayTrack:
    def test_success(self, mock_client):
        with patch("mcp_server.server.SpotifyClient", return_value=mock_client):
            from mcp_server.server import play_track

            result = play_track("abc123")
        assert "Playing" in result
        assert "abc123" in result

    def test_auth_error(self):
        with patch("mcp_server.server.SpotifyClient", side_effect=SpotifyAuthError("expired")):
            from mcp_server.server import play_track

            result = play_track("abc123")
        assert "make auth" in result


class TestQueueTrack:
    def test_success(self, mock_client):
        with patch("mcp_server.server.SpotifyClient", return_value=mock_client):
            from mcp_server.server import queue_track

            result = queue_track("def456")
        assert "Queued" in result
        assert "def456" in result

    def test_auth_error(self):
        with patch("mcp_server.server.SpotifyClient", side_effect=SpotifyAuthError("expired")):
            from mcp_server.server import queue_track

            result = queue_track("def456")
        assert "make auth" in result


class TestGetCurrentPlayback:
    def test_returns_now_playing(self, mock_client):
        with patch("mcp_server.server.SpotifyClient", return_value=mock_client):
            from mcp_server.server import get_current_playback

            result = get_current_playback()
        assert "Test Track" in result
        assert "Test Artist" in result
        assert "Playing" in result

    def test_no_active_session(self, mock_client):
        mock_client.get.return_value = {}
        with (
            patch("mcp_server.server.SpotifyClient", return_value=mock_client),
            patch("mcp_server.server.get_playback_state", return_value=None),
        ):
            from mcp_server.server import get_current_playback

            result = get_current_playback()
        assert "No active playback" in result

    def test_auth_error(self):
        with patch("mcp_server.server.SpotifyClient", side_effect=SpotifyAuthError("expired")):
            from mcp_server.server import get_current_playback

            result = get_current_playback()
        assert "make auth" in result
