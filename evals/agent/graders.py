"""Tier 3 — RAGAS faithfulness/relevancy + deterministic tool correctness.

RAGAS and answer relevancy graders are cost-gated (LLM calls via Haiku).
Tool correctness is deterministic — no LLM needed.

Usage:
    # Deterministic (no cost gate):
    score = grade_tool_correctness("q", ["search_tracks"], ["search_tracks"])

    # LLM-graded (requires CONFIRM_EXPENSIVE_OPS=true):
    score = grade_faithfulness("q", "answer text", ["context chunk 1"])
    score = grade_answer_relevancy("q", "answer text", ["context chunk 1"])
"""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic

from evals.agent.cost_gate import CONFIRM_EXPENSIVE_OPS
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

HAIKU_MODEL = "claude-haiku-4-5-20251001"


def get_ragas_llm() -> ChatAnthropic:
    """Return Haiku instance configured for RAGAS grading."""
    return ChatAnthropic(
        model=HAIKU_MODEL,
        api_key=settings.anthropic_api_key,
    )


def grade_faithfulness(
    question: str,
    answer: str,
    contexts: list[str],
) -> float:
    """RAGAS faithfulness score — measures if answer is grounded in contexts.

    Cost-gated. Returns float 0.0–1.0.
    """
    if not CONFIRM_EXPENSIVE_OPS:
        raise RuntimeError(
            "Set CONFIRM_EXPENSIVE_OPS=true env var for RAGAS faithfulness eval."
        )

    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import Faithfulness

    llm = LangchainLLMWrapper(get_ragas_llm())
    metric = Faithfulness(llm=llm)

    sample = SingleTurnSample(
        user_input=question,
        response=answer,
        retrieved_contexts=contexts,
    )
    dataset = EvaluationDataset(samples=[sample])
    result = evaluate(dataset=dataset, metrics=[metric])
    score = result.scores[0].get("faithfulness", 0.0)
    log.debug("graders.faithfulness", question=question[:80], score=score)
    return float(score)


def grade_answer_relevancy(
    question: str,
    answer: str,
    contexts: list[str],
) -> float:
    """RAGAS answer relevancy score — measures if answer addresses the question.

    Cost-gated. Returns float 0.0–1.0.
    """
    if not CONFIRM_EXPENSIVE_OPS:
        raise RuntimeError(
            "Set CONFIRM_EXPENSIVE_OPS=true env var for RAGAS answer relevancy eval."
        )

    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import AnswerRelevancy

    llm = LangchainLLMWrapper(get_ragas_llm())
    metric = AnswerRelevancy(llm=llm)

    sample = SingleTurnSample(
        user_input=question,
        response=answer,
        retrieved_contexts=contexts,
    )
    dataset = EvaluationDataset(samples=[sample])
    result = evaluate(dataset=dataset, metrics=[metric])
    score = result.scores[0].get("answer_relevancy", 0.0)
    log.debug("graders.answer_relevancy", question=question[:80], score=score)
    return float(score)


def grade_tool_correctness(
    query: str,
    expected_tools: list[str],
    actual_tools: list[str],
) -> float:
    """Deterministic tool correctness — no LLM needed.

    Returns fraction of expected tools that appear in actual tools.
    If no tools expected, returns 1.0 only if none were called.
    """
    if not expected_tools:
        return 1.0 if not actual_tools else 0.0
    matches = set(expected_tools) & set(actual_tools)
    score = len(matches) / len(expected_tools)
    log.debug(
        "graders.tool_correctness",
        query=query[:80],
        expected=expected_tools,
        actual=actual_tools,
        score=score,
    )
    return score
