"""Tests for evals/agent/graders.py — deterministic tool correctness + cost-gated RAGAS."""

from __future__ import annotations

import pytest

from evals.agent.graders import (
    grade_answer_relevancy,
    grade_faithfulness,
    grade_tool_correctness,
)

# --- grade_tool_correctness (deterministic, no LLM) ---


def test_tool_correctness_perfect_match() -> None:
    assert grade_tool_correctness("q", ["search_tracks"], ["search_tracks"]) == 1.0


def test_tool_correctness_partial() -> None:
    score = grade_tool_correctness(
        "q", ["search_tracks", "recommend_for_artist"], ["search_tracks"]
    )
    assert score == 0.5


def test_tool_correctness_no_expected_no_actual() -> None:
    assert grade_tool_correctness("q", [], []) == 1.0


def test_tool_correctness_no_expected_but_actual() -> None:
    assert grade_tool_correctness("q", [], ["search_tracks"]) == 0.0


def test_tool_correctness_superset_actual() -> None:
    """Extra tools beyond expected still counts as full match."""
    score = grade_tool_correctness("q", ["search_tracks"], ["search_tracks", "get_artist_info"])
    assert score == 1.0


def test_tool_correctness_no_overlap() -> None:
    score = grade_tool_correctness("q", ["search_tracks"], ["get_artist_info"])
    assert score == 0.0


# --- Cost-gated RAGAS graders (verify gate blocks without env var) ---


def test_faithfulness_raises_without_cost_gate() -> None:
    with pytest.raises(RuntimeError, match="CONFIRM_EXPENSIVE_OPS"):
        grade_faithfulness("question", "answer", ["context"])


def test_answer_relevancy_raises_without_cost_gate() -> None:
    with pytest.raises(RuntimeError, match="CONFIRM_EXPENSIVE_OPS"):
        grade_answer_relevancy("question", "answer", ["context"])
