from __future__ import annotations

from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from evals.agent.trajectory_eval import (
    TrajectoryResult,
    check_tool_match,
    extract_tools_from_messages,
)


class TestExtractToolsFromMessages:
    def test_extracts_tool_names(self) -> None:
        messages = [
            HumanMessage(content="query"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "search_tracks", "args": {}, "id": "1", "type": "tool_call"},
                    {"name": "get_artist_context", "args": {}, "id": "2", "type": "tool_call"},
                ],
            ),
        ]
        assert extract_tools_from_messages(messages) == [
            "search_tracks",
            "get_artist_context",
        ]

    def test_empty_when_no_tool_calls(self) -> None:
        messages = [
            HumanMessage(content="hello"),
            AIMessage(content="hi there"),
        ]
        assert extract_tools_from_messages(messages) == []

    def test_empty_list(self) -> None:
        assert extract_tools_from_messages([]) == []


class TestCheckToolMatch:
    def test_perfect_match(self) -> None:
        assert check_tool_match(["search_tracks"], ["search_tracks"]) is True

    def test_superset_match(self) -> None:
        assert check_tool_match(
            ["search_tracks"], ["search_tracks", "get_artist_context"]
        ) is True

    def test_partial_mismatch(self) -> None:
        assert check_tool_match(
            ["search_tracks", "get_artist_context"], ["search_tracks"]
        ) is False

    def test_empty_expected_empty_actual(self) -> None:
        assert check_tool_match([], []) is True

    def test_empty_expected_nonempty_actual(self) -> None:
        assert check_tool_match([], ["search_tracks"]) is False


class TestTrajectoryResult:
    def test_dataclass_fields(self) -> None:
        result = TrajectoryResult(
            sample_id="t1",
            query="test",
            actual_intent="artist_info",
            expected_intent="artist_info",
            tools_called=["search_tracks"],
            expected_tools=["search_tracks"],
            tool_match=True,
            intent_match=True,
        )
        assert result.sample_id == "t1"
        assert result.tool_match is True
        assert result.node_sequence == []


class TestEvaluateTrajectory:
    def test_raises_without_cost_gate(self) -> None:
        with patch("evals.agent.trajectory_eval.CONFIRM_EXPENSIVE_OPS", False):
            from evals.agent.trajectory_eval import evaluate_trajectory

            with pytest.raises(RuntimeError, match="CONFIRM_EXPENSIVE_OPS"):
                import asyncio

                asyncio.get_event_loop().run_until_complete(
                    evaluate_trajectory([], None)
                )
