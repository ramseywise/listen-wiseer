"""Unit tests for agent tool definitions — the ALL_TOOLS registry and web_search tools.

Behaviour of the discover / music / recommend tools lives in their own test modules.
"""

from __future__ import annotations

from unittest.mock import patch


class TestAllTools:
    def test_expected_tools_present(self) -> None:
        from agent.tools import ALL_TOOLS

        tool_names = {t.name for t in ALL_TOOLS}
        expected = {
            "discover_tracks",
            "play_track",
            "save_playlist",
            "get_user_playlists",
            "get_top_tracks",
            "get_top_artists",
            "get_taste_analysis",
            "get_related_artists",
            "get_artist_info",
            "get_artist_top_tracks",
            "get_artist_albums",
            "get_artist_context",
            "get_genre_context",
        }
        assert expected <= tool_names

    def test_no_spotify_tools(self) -> None:
        from agent.tools import ALL_TOOLS

        tool_names = {t.name for t in ALL_TOOLS}
        assert not tool_names & {"get_spotify_recommendations", "create_playlist"}

    def test_all_tools_count(self) -> None:
        from agent.tools import ALL_TOOLS

        assert len(ALL_TOOLS) == 21

    def test_tool_names_unique(self) -> None:
        from agent.tools import ALL_TOOLS

        names = [t.name for t in ALL_TOOLS]
        assert len(names) == len(set(names))


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
