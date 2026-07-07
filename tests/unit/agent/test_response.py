"""Unit tests for final response formatting."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.response import format_response


def _tool_message(
    content: str, artifact: dict | None, name: str = "get_artist_context"
) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id="call1", name=name, artifact=artifact)


class TestFormatResponse:
    def test_no_ai_message_returns_empty(self) -> None:
        state = {"messages": [HumanMessage(content="hi")]}
        assert format_response(state) == {}

    def test_extracts_track_list_and_message(self) -> None:
        state = {
            "messages": [
                HumanMessage(content="recommend tracks"),
                AIMessage(content="Here you go:\n1. Track A\n2. Track B"),
            ],
            "intent": "recommendation",
        }
        result = format_response(state)
        assert result["agent_response"]["track_list"] == ["Track A", "Track B"]
        assert "recommendation" not in result["agent_response"]  # sanity: no stray key
        assert result["agent_response"]["suggestions"]

    def test_surfaces_sources_from_current_turn_tool_message(self) -> None:
        state = {
            "messages": [
                HumanMessage(content="who is Aphex Twin?"),
                AIMessage(
                    content="", tool_calls=[{"name": "get_artist_context", "args": {}, "id": "1"}]
                ),
                _tool_message(
                    "Aphex Twin bio...",
                    artifact={
                        "sources": [{"title": "Wiki", "url": "https://x.test/aphex"}],
                        "confidence": "high",
                    },
                ),
                AIMessage(content="Aphex Twin is an English electronic musician."),
            ],
            "intent": "artist_info",
        }
        result = format_response(state)
        assert result["agent_response"]["sources"] == [
            {"title": "Wiki", "url": "https://x.test/aphex"}
        ]

    def test_does_not_leak_sources_from_a_prior_turn(self) -> None:
        """Regression: a previous turn's web-search citations must not attach
        to the current turn's answer just because they're earlier in history."""
        state = {
            "messages": [
                HumanMessage(content="who is Aphex Twin?"),
                AIMessage(
                    content="", tool_calls=[{"name": "get_artist_context", "args": {}, "id": "1"}]
                ),
                _tool_message(
                    "Aphex Twin bio...",
                    artifact={
                        "sources": [{"title": "Wiki", "url": "https://x.test/aphex"}],
                        "confidence": "high",
                    },
                ),
                AIMessage(content="Aphex Twin is an English electronic musician."),
                HumanMessage(content="recommend me some zouk tracks"),
                AIMessage(content="1. Track A\n2. Track B"),
            ],
            "intent": "recommendation",
        }
        result = format_response(state)
        assert result["agent_response"]["sources"] == []

    def test_deduplicates_sources_by_url(self) -> None:
        state = {
            "messages": [
                HumanMessage(content="who is Aphex Twin?"),
                _tool_message(
                    "hit 1",
                    artifact={
                        "sources": [{"title": "A", "url": "https://x.test/1"}],
                        "confidence": "high",
                    },
                ),
                _tool_message(
                    "hit 2",
                    artifact={
                        "sources": [{"title": "A dup", "url": "https://x.test/1"}],
                        "confidence": "high",
                    },
                ),
                AIMessage(content="answer"),
            ],
            "intent": "artist_info",
        }
        result = format_response(state)
        # Walk is newest-first, so the later tool message's title wins the dedup.
        assert result["agent_response"]["sources"] == [{"title": "A dup", "url": "https://x.test/1"}]

    def test_ignores_non_dict_artifact(self) -> None:
        """Non-web-search tools return plain strings with no artifact — must not crash."""
        state = {
            "messages": [
                HumanMessage(content="what are my top tracks?"),
                _tool_message("1. Track A", artifact=None, name="get_top_tracks"),
                AIMessage(content="1. Track A"),
            ],
            "intent": "history",
        }
        result = format_response(state)
        assert result["agent_response"]["sources"] == []
