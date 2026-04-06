from __future__ import annotations

import pytest

from evals.agent.intent_eval import evaluate_intent, evaluate_routing
from evals.tasks.models import AgentGoldenSample


def _make_sample(
    sample_id: str,
    query: str,
    expected_intent: str,
    expected_route: str = "rewrite_query",
    **kwargs: object,
) -> AgentGoldenSample:
    return AgentGoldenSample(
        sample_id=sample_id,
        query=query,
        expected_intent=expected_intent,
        expected_route=expected_route,
        **kwargs,
    )


class TestEvaluateIntent:
    def test_perfect_accuracy(self) -> None:
        samples = [
            _make_sample("t1", "Tell me about Radiohead and their influences", "artist_info"),
            _make_sample("t2", "What is ambient music and explain its origins?", "genre_info"),
        ]
        metrics = evaluate_intent(samples)
        assert metrics.accuracy == 1.0
        assert metrics.n_samples == 2

    def test_partial_accuracy(self) -> None:
        samples = [
            _make_sample("t1", "Tell me about Radiohead and their influences", "artist_info"),
            _make_sample("t2", "Tell me about Radiohead and their influences", "genre_info"),
        ]
        metrics = evaluate_intent(samples)
        assert metrics.accuracy == 0.5

    def test_confusion_matrix_populated(self) -> None:
        samples = [
            _make_sample("t1", "Hello!", "chit_chat"),
            _make_sample("t2", "Hey, how are you?", "chit_chat"),
        ]
        metrics = evaluate_intent(samples)
        assert "chit_chat" in metrics.confusion
        assert metrics.confusion["chit_chat"]["chit_chat"] == 2

    def test_f1_scores_present(self) -> None:
        samples = [
            _make_sample("t1", "Hello!", "chit_chat"),
            _make_sample("t2", "Recommend tracks similar to Bohemian Rhapsody", "recommendation"),
        ]
        metrics = evaluate_intent(samples)
        assert "chit_chat" in metrics.per_intent_f1
        assert "recommendation" in metrics.per_intent_f1

    def test_confidence_threshold_in_metrics(self) -> None:
        samples = [_make_sample("t1", "Hello!", "chit_chat")]
        metrics = evaluate_intent(samples)
        assert metrics.confidence_threshold == pytest.approx(0.4)


class TestEvaluateRouting:
    def test_chit_chat_routes_to_rewrite(self) -> None:
        samples = [
            _make_sample("t1", "Hello!", "chit_chat", expected_route="rewrite_query"),
        ]
        result = evaluate_routing(samples)
        assert result["route_accuracy"] == 1.0

    def test_low_confidence_routes_to_clarify(self) -> None:
        # Single keyword match → confidence 0.33 < 0.4 → clarify_or_proceed
        samples = [
            _make_sample(
                "t1",
                "Who is Aphex Twin?",
                "artist_info",
                expected_route="clarify_or_proceed",
            ),
        ]
        result = evaluate_routing(samples)
        assert result["route_accuracy"] == 1.0

    def test_high_confidence_routes_to_rewrite(self) -> None:
        # Two keyword matches → confidence 0.67 > 0.4 → rewrite_query
        samples = [
            _make_sample(
                "t1",
                "Tell me about Radiohead and their influences",
                "artist_info",
                expected_route="rewrite_query",
            ),
        ]
        result = evaluate_routing(samples)
        assert result["route_accuracy"] == 1.0

    def test_n_samples_in_result(self) -> None:
        samples = [
            _make_sample("t1", "Hello!", "chit_chat"),
            _make_sample("t2", "Hey thanks!", "chit_chat"),
        ]
        result = evaluate_routing(samples)
        assert result["n_samples"] == 2
