"""Runtime answer checker for the agent's verification loop.

Deterministic, no LLM, no cost gate — safe to call inside the LangGraph graph.
The offline LLM-as-judge evaluator lives in ``evals.graders.answer_eval`` and
re-exports these names.
"""

from __future__ import annotations

from dataclasses import dataclass

from utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class JudgeResult:
    """Result from a single AnswerJudge evaluation."""

    is_correct: bool
    score: float
    faithfulness: float
    relevance: float
    completeness: float
    reasoning: str
    query_id: str = ""


class HeuristicChecker:
    """Tier-1 heuristic answer checker — deterministic, no LLM, no cost gate.

    Returns a ``JudgeResult`` using rule-based signals:
    - **groundedness**: answer references at least one entity from the question
    - **non-empty**: answer is substantively non-empty
    - **used_context**: tool output text appears (partially) in the conversation

    Use this inside the LangGraph verification loop where cost-gated LLM calls
    are not appropriate. LLM-based evaluation belongs in the offline eval harness
    (``AnswerJudge``).
    """

    MIN_ANSWER_CHARS = 20

    def check(
        self,
        query_id: str,
        question: str,
        answer: str,
        tool_outputs: list[str],
    ) -> JudgeResult:
        """Check a final answer against the originating question and tool outputs.

        Args:
            query_id:     Identifier for logging.
            question:     The original user question.
            answer:       The generated answer to check.
            tool_outputs: Text content from all tool messages in this turn.

        Returns:
            JudgeResult with heuristic scores and reasoning.
        """
        answer_lower = answer.lower().strip()
        question_lower = question.lower()

        # 1. Non-empty
        non_empty = len(answer_lower) >= self.MIN_ANSWER_CHARS
        non_empty_score = 1.0 if non_empty else 0.0

        # 2. Groundedness — at least one significant word from the question appears
        #    in the answer (filters stopwords by length >= 4)
        question_keywords = {w for w in question_lower.split() if len(w) >= 4}
        if question_keywords:
            matched_kw = sum(1 for kw in question_keywords if kw in answer_lower)
            groundedness = matched_kw / len(question_keywords)
        else:
            groundedness = 1.0  # no keywords to check

        # 3. Context use — some overlap between tool output words and answer
        if tool_outputs:
            all_tool_text = " ".join(tool_outputs).lower()
            tool_words = {w for w in all_tool_text.split() if len(w) >= 5}
            if tool_words:
                answer_words = set(answer_lower.split())
                overlap = len(tool_words & answer_words) / len(tool_words)
                context_use = min(1.0, overlap * 5)  # generous scaling
            else:
                context_use = 0.5  # tool ran but no extractable words
        else:
            context_use = 0.5  # no tool outputs — neutral (chit_chat path)

        overall = (non_empty_score + groundedness + context_use) / 3.0
        is_correct = non_empty and groundedness >= 0.2

        reasoning_parts = []
        if not non_empty:
            reasoning_parts.append("answer too short")
        if groundedness < 0.2:
            reasoning_parts.append("answer does not reference query terms")
        if context_use < 0.1 and tool_outputs:
            reasoning_parts.append("answer lacks overlap with tool output")
        reasoning = (
            "; ".join(reasoning_parts) if reasoning_parts else "answer passes heuristic checks"
        )

        result = JudgeResult(
            is_correct=is_correct,
            score=round(overall, 3),
            faithfulness=round(context_use, 3),
            relevance=round(groundedness, 3),
            completeness=round(non_empty_score, 3),
            reasoning=reasoning,
            query_id=query_id,
        )
        log.debug(
            "heuristic_checker.done",
            query_id=query_id,
            score=result.score,
            is_correct=result.is_correct,
        )
        return result
