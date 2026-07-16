"""LLM-based answer evaluation (faithfulness, relevance, hallucination).

Two evaluation modes:

    AnswerJudge          — per-sample LLM-as-judge. Returns JudgeResult with
                           is_correct, score (0-1), and reasoning. Uses Haiku
                           for cost efficiency.

    ClosedBookBaseline   — runs the same questions WITHOUT retrieval context,
                           letting the LLM answer from parametric knowledge only.
                           Useful for measuring retrieval lift.

Cost gate: CONFIRM_EXPENSIVE_OPS must be True to run either. Estimated cost:
~$0.01-0.03 per sample with Haiku. Controlled via env var (see cost_gate.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import anthropic
from utils.logging import get_logger

from evals.agent.cost_gate import CONFIRM_EXPENSIVE_OPS

log = get_logger(__name__)

HAIKU_MODEL = "claude-haiku-4-5-20251001"

_JUDGE_SYSTEM = """\
You are an expert evaluator for a customer support RAG system.
You will be given a user question, the retrieved context chunks, and the
system's generated answer. Evaluate the answer on three dimensions:

1. faithfulness   — does the answer only make claims supported by the context?
2. relevance      — does the answer address the user's question?
3. completeness   — does the answer cover the key points needed to resolve the question?

Return ONLY a JSON object with these exact keys:
{
  "is_correct": <true if the answer is both faithful and relevant, else false>,
  "score": <float 0.0–1.0, overall quality>,
  "faithfulness": <float 0.0–1.0>,
  "relevance": <float 0.0–1.0>,
  "completeness": <float 0.0–1.0>,
  "reasoning": <one sentence explaining the score>
}
No other text outside the JSON object."""

_JUDGE_USER_TMPL = """\
Question: {question}

Retrieved context:
{context}

Generated answer:
{answer}"""


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


class AnswerJudge:
    """LLM-as-judge evaluator for RAG answer quality.

    Args:
        model: Anthropic model ID. Defaults to Haiku for cost efficiency.
        max_context_chars: Truncate context to this many characters to keep
                           prompts within token budget.
    """

    def __init__(
        self,
        model: str = HAIKU_MODEL,
        max_context_chars: int = 3000,
    ) -> None:
        self._client = anthropic.Anthropic()
        self._model = model
        self._max_context_chars = max_context_chars

    def evaluate(
        self,
        query_id: str,
        question: str,
        context_chunks: list[str],
        answer: str,
    ) -> JudgeResult:
        """Evaluate a single answer against its retrieved context.

        Args:
            query_id:       Identifier for logging.
            question:       The original user question.
            context_chunks: List of retrieved text chunks passed to the LLM.
            answer:         The generated answer to evaluate.

        Returns:
            JudgeResult with per-dimension scores and reasoning.
        """
        if not CONFIRM_EXPENSIVE_OPS:
            raise RuntimeError(
                "Set CONFIRM_EXPENSIVE_OPS=True to run LLM-based eval. "
                "Estimated cost: ~$0.01–0.03 per sample with Haiku."
            )

        context = "\n\n---\n\n".join(context_chunks)
        if len(context) > self._max_context_chars:
            context = context[: self._max_context_chars] + "\n[truncated]"

        user_msg = _JUDGE_USER_TMPL.format(
            question=question,
            context=context,
            answer=answer,
        )

        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system=_JUDGE_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = resp.content[0].text.strip()
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("answer_eval.judge.parse_error", query_id=query_id, error=str(exc))
            return JudgeResult(
                is_correct=False,
                score=0.0,
                faithfulness=0.0,
                relevance=0.0,
                completeness=0.0,
                reasoning="Parse error — LLM did not return valid JSON.",
                query_id=query_id,
            )
        except anthropic.APIError as exc:
            log.error("answer_eval.judge.api_error", query_id=query_id, error=str(exc))
            return JudgeResult(
                is_correct=False,
                score=0.0,
                faithfulness=0.0,
                relevance=0.0,
                completeness=0.0,
                reasoning=f"API error: {exc}",
                query_id=query_id,
            )

        result = JudgeResult(
            is_correct=bool(data.get("is_correct", False)),
            score=float(data.get("score", 0.0)),
            faithfulness=float(data.get("faithfulness", 0.0)),
            relevance=float(data.get("relevance", 0.0)),
            completeness=float(data.get("completeness", 0.0)),
            reasoning=str(data.get("reasoning", "")),
            query_id=query_id,
        )
        log.debug(
            "answer_eval.judge.done",
            query_id=query_id,
            score=result.score,
            is_correct=result.is_correct,
        )
        return result

    def evaluate_batch(
        self,
        samples: list[dict[str, Any]],
    ) -> list[JudgeResult]:
        """Evaluate a batch of samples.

        Each sample dict must have keys:
            query_id, question, context_chunks (list[str]), answer (str).

        Returns results in the same order as input.
        """
        results = []
        for sample in samples:
            result = self.evaluate(
                query_id=sample["query_id"],
                question=sample["question"],
                context_chunks=sample["context_chunks"],
                answer=sample["answer"],
            )
            results.append(result)
        return results


class ClosedBookBaseline:
    """Ask questions without retrieval context to measure parametric knowledge.

    Compare against AnswerJudge results to quantify retrieval lift:
        lift = rag_score - closed_book_score

    Args:
        model: Anthropic model ID.
    """

    _SYSTEM = (
        "You are a customer support assistant. Answer the user's question "
        "as best you can from your own knowledge. If you are unsure, say so."
    )

    def __init__(self, model: str = HAIKU_MODEL) -> None:
        self._client = anthropic.Anthropic()
        self._model = model

    def answer(self, question: str) -> str:
        """Generate a closed-book answer (no retrieval context)."""
        if not CONFIRM_EXPENSIVE_OPS:
            raise RuntimeError("Set CONFIRM_EXPENSIVE_OPS=True to run closed-book baseline.")
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=512,
            system=self._SYSTEM,
            messages=[{"role": "user", "content": question}],
        )
        return resp.content[0].text.strip()
