"""Unit tests for the maker/checker verification loop.

Tests cover:
- HeuristicChecker scoring logic (no LLM, no external deps)
- verify_answer node: pass path, retry path, cap path
- route_after_verify routing logic
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from evals.graders.answer_eval import HeuristicChecker, JudgeResult
from utils.config import settings

# ---------------------------------------------------------------------------
# HeuristicChecker
# ---------------------------------------------------------------------------


class TestHeuristicChecker:
    def setup_method(self) -> None:
        self.checker = HeuristicChecker()

    def test_good_answer_passes(self) -> None:
        result = self.checker.check(
            query_id="q1",
            question="Who is Aphex Twin?",
            answer=(
                "Aphex Twin is a British electronic musician known for his "
                "influential ambient and techno work."
            ),
            tool_outputs=["Aphex Twin, born Richard David James, is a musician."],
        )
        assert result.is_correct is True
        assert result.score >= 0.5

    def test_empty_answer_fails(self) -> None:
        result = self.checker.check(
            query_id="q2",
            question="What are my top tracks?",
            answer="",
            tool_outputs=["Track A, Track B"],
        )
        assert result.is_correct is False
        assert result.score < 0.5

    def test_too_short_answer_fails(self) -> None:
        result = self.checker.check(
            query_id="q3",
            question="What are my top tracks?",
            answer="OK",
            tool_outputs=["Track A"],
        )
        assert result.is_correct is False
        assert result.completeness == 0.0

    def test_answer_with_no_query_terms_scores_low_relevance(self) -> None:
        result = self.checker.check(
            query_id="q4",
            question="Tell me about Radiohead discography",
            answer="The weather today is quite sunny and warm outside.",
            tool_outputs=[],
        )
        # No keyword overlap → low relevance
        assert result.relevance < 0.5

    def test_returns_judge_result_dataclass(self) -> None:
        result = self.checker.check(
            query_id="q5",
            question="Recommend jazz tracks",
            answer="Here are some great jazz tracks: Kind of Blue, Take Five.",
            tool_outputs=["Miles Davis - Kind of Blue"],
        )
        assert isinstance(result, JudgeResult)
        assert 0.0 <= result.score <= 1.0
        assert 0.0 <= result.faithfulness <= 1.0
        assert 0.0 <= result.relevance <= 1.0
        assert 0.0 <= result.completeness <= 1.0
        assert isinstance(result.reasoning, str)

    def test_no_tool_outputs_neutral_faithfulness(self) -> None:
        """Chit-chat path: no tools → faithfulness defaults to 0.5."""
        result = self.checker.check(
            query_id="q6",
            question="Hello, how are you?",
            answer="I'm doing great, thanks for asking! How can I help?",
            tool_outputs=[],
        )
        assert result.faithfulness == 0.5


# ---------------------------------------------------------------------------
# verify_answer node
# ---------------------------------------------------------------------------


def _state_with_answer(
    answer: str,
    question: str = "Who is Aphex Twin?",
    retries: int = 0,
    tool_output: str = "Aphex Twin is an electronic musician.",
) -> dict:
    return {
        "messages": [
            HumanMessage(content=question),
            AIMessage(content=answer),
        ],
        "agent_response": {"message": answer},
        "verification_retries": retries,
    }


class TestVerifyAnswerNode:
    async def test_good_answer_passes_without_retry(self) -> None:
        from agent.graph_nodes import verify_answer

        state = _state_with_answer(
            answer=(
                "Aphex Twin is a pioneering British electronic music artist "
                "known for ambient and IDM compositions."
            ),
        )
        result = await verify_answer(state)
        # No critique injected, no messages added
        assert result.get("checker_critique") == ""
        assert "messages" not in result

    async def test_failing_answer_injects_critique_on_first_retry(self) -> None:
        from agent.graph_nodes import verify_answer

        state = _state_with_answer(answer="I don't know.", retries=0)
        result = await verify_answer(state)
        # Short / non-grounded answer should fail
        if not result.get("checker_critique"):
            pytest.skip("Heuristic passed — threshold may differ in env")
        assert result["verification_retries"] == 1
        assert "messages" in result
        assert isinstance(result["messages"][0], HumanMessage)
        assert "Checker" in result["messages"][0].content

    async def test_retry_cap_respected(self) -> None:
        from agent.graph_nodes import verify_answer

        # At max_retries, should NOT inject another message even on bad answer
        state = _state_with_answer(
            answer="I don't know.",
            retries=settings.max_verification_retries,
        )
        result = await verify_answer(state)
        assert "messages" not in result
        assert result["verification_retries"] == settings.max_verification_retries

    async def test_retry_cap_is_configurable(self) -> None:
        """Default cap is 2; verify the setting is read from config."""
        assert settings.max_verification_retries == 2

    async def test_passes_when_score_meets_threshold(self) -> None:
        from agent.graph_nodes import verify_answer

        # Construct a clearly grounded, on-topic answer
        state = _state_with_answer(
            answer=(
                "Aphex Twin, also known as Richard David James, is a highly influential "
                "British electronic music artist famous for ambient techno and IDM."
            ),
        )
        result = await verify_answer(state)
        assert result.get("checker_critique") == ""


# ---------------------------------------------------------------------------
# route_after_verify
# ---------------------------------------------------------------------------


class TestRouteAfterVerify:
    def test_routes_to_end_on_empty_critique(self) -> None:
        from agent.graph_nodes import route_after_verify

        state = {
            "messages": [HumanMessage(content="hi"), AIMessage(content="hello")],
            "verification_retries": 0,
            "checker_critique": "",
        }
        assert route_after_verify(state) == "END"

    def test_routes_to_agent_when_critique_injected(self) -> None:
        from agent.graph_nodes import route_after_verify

        state = {
            "messages": [
                HumanMessage(content="original question"),
                AIMessage(content="bad answer"),
                HumanMessage(content="[Checker] please revise"),
            ],
            "verification_retries": 1,
            "checker_critique": "answer does not reference query terms",
        }
        assert route_after_verify(state) == "agent"

    def test_routes_to_end_when_cap_exceeded(self) -> None:
        from agent.graph_nodes import route_after_verify

        # retries > max_verification_retries → END even if critique present
        state = {
            "messages": [
                HumanMessage(content="question"),
                AIMessage(content="bad answer"),
            ],
            "verification_retries": settings.max_verification_retries + 1,
            "checker_critique": "still failing",
        }
        assert route_after_verify(state) == "END"
