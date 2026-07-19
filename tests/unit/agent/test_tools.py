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

        assert len(ALL_TOOLS) == 20

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


class TestGetTasteAnalysis:
    def test_new_obsessions_stable_fading(self) -> None:
        short_artists = [{"name": "New Artist"}, {"name": "Stable Artist"}]
        long_artists = [{"name": "Stable Artist"}, {"name": "Fading Artist"}]
        with (
            patch(
                "agent.tools.spotify_read.fetch_top_artists",
                side_effect=[short_artists, long_artists],
            ),
            patch("agent.tools.spotify_read._get_client", return_value=MagicMock()),
        ):
            from agent.tools.spotify_read import _get_taste_analysis

            result = _get_taste_analysis()

        assert "New Artist" in result
        assert "Stable Artist" in result
        assert "Fading Artist" in result
        assert "New obsessions" in result
        assert "Consistent staples" in result
        assert "Fading interests" in result

    def test_empty_short_term(self) -> None:
        with (
            patch(
                "agent.tools.spotify_read.fetch_top_artists",
                side_effect=[[], [{"name": "Old Fave"}]],
            ),
            patch("agent.tools.spotify_read._get_client", return_value=MagicMock()),
        ):
            from agent.tools.spotify_read import _get_taste_analysis

            result = _get_taste_analysis()

        assert "Old Fave" in result

    def test_get_taste_analysis_in_all_tools(self) -> None:
        from agent.tools import ALL_TOOLS

        tool_names = [t.name for t in ALL_TOOLS]
        assert "get_taste_analysis" in tool_names


class TestGetGenreContext:
    def test_get_genre_context_in_all_tools(self) -> None:
        from agent.tools import ALL_TOOLS

        tool_names = [t.name for t in ALL_TOOLS]
        assert "get_genre_context" in tool_names

    def test_genre_context_query_structure(self) -> None:
        """Genre context uses genre-specific query template, not generic artist bio."""
        captured: list[str] = []

        def fake_agentic_search(subject: str, query: str, wiki_query: str | None = None) -> tuple:
            captured.append(query)
            return ("result text", {"sources": [], "confidence": "high"})

        with patch("agent.tools.web_search._agentic_search", side_effect=fake_agentic_search):
            from agent.tools.web_search import _get_genre_context

            _get_genre_context("bossa nova")

        assert captured, "agentic_search was not called"
        assert "origins" in captured[0]
        assert "key artists" in captured[0]
        assert "subgenres" in captured[0]
        # Must NOT use the artist biography template
        assert "biography" not in captured[0]
