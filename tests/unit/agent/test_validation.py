"""Unit tests for post-tool-output validation.

agent.validation has no DuckDB dependency, so it's imported directly (unlike
agent.graph_nodes, which pulls in the Spotify/recommend tool chain).
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from agent.validation import validate_tool_output


def _tool_message(
    content: str, artifact: dict | None = None, name: str = "get_artist_context"
) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id="call1", name=name, artifact=artifact)


class TestValidateToolOutput:
    async def test_passes_through_when_no_tool_messages(self) -> None:
        state = {"messages": [HumanMessage(content="hi")]}
        # No tool messages → no stall tracking, empty return
        assert await validate_tool_output(state) == {}

    async def test_passes_through_on_high_confidence_artifact(self) -> None:
        state = {
            "messages": [
                HumanMessage(content="who is Aphex Twin?"),
                _tool_message("Aphex Twin is...", artifact={"sources": [], "confidence": "high"}),
            ],
            "intent": "artist_info",
        }
        result = await validate_tool_output(state)
        # No issues: stall tracking fields are returned, no messages/retries
        assert "messages" not in result
        assert "tool_validation_retries" not in result
        assert "last_tool_call_sequence" in result
        assert "stall_count" in result

    async def test_low_confidence_artifact_injects_corrective_hint(self) -> None:
        state = {
            "messages": [
                HumanMessage(content="who is Some Fictional Artist?"),
                _tool_message(
                    "I couldn't find reliable information on 'Some Fictional Artist'.",
                    artifact={"sources": [], "confidence": "low"},
                ),
            ],
            "intent": "artist_info",
            "tool_validation_retries": 0,
        }
        result = await validate_tool_output(state)
        assert "messages" in result
        assert isinstance(result["messages"][0], SystemMessage)
        assert "low-confidence" in result["messages"][0].content.lower()
        assert result["tool_validation_retries"] == 1

    async def test_low_confidence_hint_suppressed_after_retries_exhausted(self) -> None:
        state = {
            "messages": [
                HumanMessage(content="who is Some Fictional Artist?"),
                _tool_message(
                    "I couldn't find reliable information.",
                    artifact={"sources": [], "confidence": "low"},
                ),
            ],
            "intent": "artist_info",
            "tool_validation_retries": 1,  # settings.max_tool_validation_retries default is 1
        }
        result = await validate_tool_output(state)
        # Retries exhausted: passes through with stall tracking only
        assert "messages" not in result
        assert "tool_validation_retries" not in result

    async def test_ignores_artifact_that_is_not_a_dict(self) -> None:
        """Non-web-search tools return plain strings with no artifact — must not crash."""
        state = {
            "messages": [
                HumanMessage(content="what are my top tracks?"),
                _tool_message("1. Track A\n2. Track B", artifact=None, name="get_top_tracks"),
            ],
            "intent": "history",
        }
        result = await validate_tool_output(state)
        assert "messages" not in result
        assert "tool_validation_retries" not in result

    async def test_stall_detected_after_threshold(self) -> None:
        """Identical tool sequence repeated stall_detection_threshold times → stall hint."""
        same_tool = _tool_message("some output", name="get_top_tracks")
        state = {
            "messages": [HumanMessage(content="what's trending?"), same_tool],
            "intent": "history",
            "last_tool_call_sequence": ["get_top_tracks"],
            "stall_count": 2,  # already at threshold - 1; this call pushes to threshold (3)
        }
        result = await validate_tool_output(state)
        assert "messages" in result
        assert isinstance(result["messages"][0], SystemMessage)
        assert "stall" in result["messages"][0].content.lower()
        assert result["stall_count"] == 3

    async def test_stall_resets_on_different_sequence(self) -> None:
        """Different tool used → stall count resets to 0."""
        state = {
            "messages": [
                HumanMessage(content="what's trending?"),
                _tool_message("output", name="get_top_artists"),
            ],
            "intent": "history",
            "last_tool_call_sequence": ["get_top_tracks"],  # different from current
            "stall_count": 2,
        }
        result = await validate_tool_output(state)
        assert result["stall_count"] == 0
        assert result["last_tool_call_sequence"] == ["get_top_artists"]
