"""Tier 1 — Deterministic intent classification and route evaluation.

No LLM calls. Imports QueryAnalyzer directly to avoid the DuckDB import chain
that agent.nodes would trigger.
"""

from __future__ import annotations

from collections import defaultdict

from evals.tasks.models import AgentGoldenSample, IntentEvalMetrics
from rag_core.orchestration.query_understanding import QueryAnalyzer
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

_analyzer = QueryAnalyzer()


def evaluate_intent(samples: list[AgentGoldenSample]) -> IntentEvalMetrics:
    """Run deterministic intent classification eval against golden samples.

    Returns accuracy, per-intent F1, and a confusion matrix.
    No LLM calls — fully deterministic keyword matching.
    """
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    correct = 0

    for sample in samples:
        result = _analyzer.analyze(sample.query)
        predicted = result.intent
        expected = sample.expected_intent
        confusion[expected][predicted] += 1
        if predicted == expected:
            correct += 1

    all_intents = sorted({s.expected_intent for s in samples})
    f1_scores = _compute_per_intent_f1(confusion, all_intents)

    metrics = IntentEvalMetrics(
        accuracy=correct / len(samples),
        per_intent_f1=f1_scores,
        confusion={k: dict(v) for k, v in confusion.items()},
        n_samples=len(samples),
        confidence_threshold=settings.intent_confidence_threshold,
    )
    log.info(
        "eval.intent.complete",
        accuracy=metrics.accuracy,
        n_samples=metrics.n_samples,
    )
    return metrics


def _compute_per_intent_f1(
    confusion: dict[str, dict[str, int]],
    intents: list[str],
) -> dict[str, float]:
    """Compute per-intent F1 from a confusion matrix."""
    f1_scores: dict[str, float] = {}

    for intent in intents:
        tp = confusion.get(intent, {}).get(intent, 0)

        # FP: predicted as this intent but expected something else
        fp = sum(
            confusion.get(other, {}).get(intent, 0)
            for other in intents
            if other != intent
        )

        # FN: expected this intent but predicted something else
        fn = sum(
            count
            for predicted, count in confusion.get(intent, {}).items()
            if predicted != intent
        )

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        if precision + recall > 0:
            f1_scores[intent] = 2 * precision * recall / (precision + recall)
        else:
            f1_scores[intent] = 0.0

    return f1_scores


def _route_after_classify(intent: str, confidence: float) -> str:
    """Replicated from agent.nodes — avoids DuckDB import chain."""
    if intent == "chit_chat":
        return "rewrite_query"
    if confidence < settings.intent_confidence_threshold:
        return "clarify_or_proceed"
    return "rewrite_query"


def evaluate_routing(samples: list[AgentGoldenSample]) -> dict[str, float | int]:
    """Check route matches expected_route for each sample.

    Uses replicated routing logic (not imported from agent.nodes)
    to avoid the DuckDB import chain.
    """
    correct = 0
    for sample in samples:
        result = _analyzer.analyze(sample.query)
        predicted_route = _route_after_classify(result.intent, result.confidence)
        if predicted_route == sample.expected_route:
            correct += 1

    accuracy = correct / len(samples)
    log.info("eval.routing.complete", route_accuracy=accuracy, n_samples=len(samples))
    return {"route_accuracy": accuracy, "n_samples": len(samples)}
