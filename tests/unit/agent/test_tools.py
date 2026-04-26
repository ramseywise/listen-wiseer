"""Unit tests for agent tool definitions.

Tests the current module-split structure: agent.tools is a package with
spotify_read, spotify_write, recommend, memory, web_search submodules.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestAllTools:
    def test_get_artist_context_tool_in_all_tools(self) -> None:
        from agent.tools import ALL_TOOLS

        tool_names = [t.name for t in ALL_TOOLS]
        assert "get_artist_context" in tool_names

    def test_get_related_artists_in_all_tools(self) -> None:
        from agent.tools import ALL_TOOLS

        tool_names = [t.name for t in ALL_TOOLS]
        assert "get_related_artists" in tool_names

    def test_all_exploration_tools_present(self) -> None:
        from agent.tools import ALL_TOOLS

        tool_names = {t.name for t in ALL_TOOLS}
        expected = {
            "get_top_tracks",
            "get_top_artists",
            "get_artist_info",
            "get_artist_top_tracks",
            "get_artist_albums",
            "get_user_playlists",
            "get_spotify_recommendations",
        }
        assert expected <= tool_names

    def test_all_tools_count(self) -> None:
        from agent.tools import ALL_TOOLS

        assert len(ALL_TOOLS) == 18

    def test_create_playlist_in_all_tools(self) -> None:
        from agent.tools import ALL_TOOLS

        tool_names = [t.name for t in ALL_TOOLS]
        assert "create_playlist" in tool_names


class TestGetRelatedArtists:
    def test_formats_output_with_genres(self) -> None:
        mock_artists = [
            {"id": "a1", "name": "Artist A", "genres": ["rock", "indie"]},
            {"id": "a2", "name": "Artist B", "genres": []},
        ]
        with (
            patch("agent.tools.spotify_read.fetch_related_artists", return_value=mock_artists),
            patch("agent.tools.spotify_read._get_client", return_value=MagicMock()),
        ):
            from agent.tools.spotify_read import _get_related_artists

            result = _get_related_artists("seed_id")

        assert "Artist A" in result
        assert "rock, indie" in result
        assert "Artist B" in result
        assert "unknown genre" in result


