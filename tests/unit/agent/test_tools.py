"""Unit tests for agent tool definitions.

The agent.tools module eagerly loads RecommendationEngine (which requires
DuckDB + model files). Tests mock at the module level to avoid this chain.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_get_artist_context_calls_music_rag():
    """_get_artist_context delegates to MusicRAG.get_context."""
    mock_rag = MagicMock()
    mock_rag.get_context.return_value = "Richard David James is a musician."

    with patch("agent.tools._music_rag", mock_rag):
        from agent.tools import _get_artist_context

        result = _get_artist_context("Aphex Twin")

    assert result == "Richard David James is a musician."
    mock_rag.get_context.assert_called_once_with("Aphex Twin")


def test_get_artist_context_lazy_init():
    """MusicRAG is initialized lazily on first call, not at import time."""
    import agent.tools as tools_mod

    # Reset singleton to None
    original = tools_mod._music_rag
    try:
        tools_mod._music_rag = None

        mock_rag_instance = MagicMock()
        mock_rag_instance.get_context.return_value = "Some context."

        mock_module = MagicMock()
        mock_module.MusicRAG.return_value = mock_rag_instance

        with patch.dict("sys.modules", {"rag_core.orchestration.music_rag": mock_module}):
            result = tools_mod._get_artist_context("Radiohead")

        assert result == "Some context."
        assert tools_mod._music_rag is not None
    finally:
        tools_mod._music_rag = original


def test_get_artist_context_tool_in_all_tools():
    """get_artist_context_tool is present in ALL_TOOLS."""
    from agent.tools import ALL_TOOLS

    tool_names = [t.name for t in ALL_TOOLS]
    assert "get_artist_context" in tool_names


def test_all_tools_count():
    """ALL_TOOLS should have 10 tools after adding get_related_artists."""
    from agent.tools import ALL_TOOLS

    assert len(ALL_TOOLS) == 10


def test_get_related_artists_in_all_tools():
    """get_related_artists_tool is present in ALL_TOOLS."""
    from agent.tools import ALL_TOOLS

    tool_names = [t.name for t in ALL_TOOLS]
    assert "get_related_artists" in tool_names


def test_get_related_artists_formats_output():
    """_get_related_artists formats artist list into readable lines."""
    from unittest.mock import MagicMock

    mock_artists = [
        {"id": "a1", "name": "Artist A", "genres": ["rock", "indie"]},
        {"id": "a2", "name": "Artist B", "genres": []},
    ]

    with patch("agent.tools.fetch_related_artists", return_value=mock_artists), \
         patch("agent.tools._get_client", return_value=MagicMock()):
        from agent.tools import _get_related_artists

        result = _get_related_artists("seed_id")

    assert "Artist A" in result
    assert "rock, indie" in result
    assert "Artist B" in result
    assert "unknown genre" in result
