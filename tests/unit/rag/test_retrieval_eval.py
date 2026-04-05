"""Unit tests for the retrieval eval harness.

Uses a synthetic golden set of 5 samples and a mock retrieve_fn that
returns known results so metrics can be verified exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).parents[2]))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(url: str, chunk_id: str = "c1"):
    from schemas.chunks import Chunk, ChunkMetadata

    return Chunk(
        id=chunk_id,
        text="Some help text.",
        metadata=ChunkMetadata(
            url=url,
            title="Article",
            section="general",
            doc_id="doc1",
        ),
    )


def _make_result(url: str, score: float = 0.9, chunk_id: str = "c1"):
    from schemas.retrieval import RetrievalResult

    return RetrievalResult(chunk=_make_chunk(url, chunk_id), score=score)


def _make_sample(query_id: str, query: str, expected_url: str):
    from evals.tasks.models import GoldenSample

    return GoldenSample(
        query_id=query_id,
        query=query,
        expected_doc_url=expected_url,
    )


# ---------------------------------------------------------------------------
# Metrics correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hit_rate_all_hits():
    """hit_rate_at_k = 1.0 when every expected URL appears in results."""
    from evals.metrics.retrieval_eval import evaluate_retrieval

    url = "https://help.example.com/article/1"
    golden = [_make_sample(f"q{i}", f"Query {i}", url) for i in range(5)]

    retrieve_fn = AsyncMock(return_value=[_make_result(url)])
    metrics, _ = await evaluate_retrieval(golden, retrieve_fn, k=5)

    assert metrics.hit_rate_at_k == 1.0
    assert metrics.n_queries == 5
    assert metrics.k == 5


@pytest.mark.asyncio
async def test_hit_rate_no_hits():
    """hit_rate_at_k = 0.0 when the expected URL is never retrieved."""
    from evals.metrics.retrieval_eval import evaluate_retrieval

    golden = [_make_sample("q1", "Query 1", "https://help.example.com/target")]
    retrieve_fn = AsyncMock(return_value=[_make_result("https://help.example.com/other")])
    metrics, _ = await evaluate_retrieval(golden, retrieve_fn, k=5)

    assert metrics.hit_rate_at_k == 0.0


@pytest.mark.asyncio
async def test_hit_rate_partial():
    """hit_rate_at_k = 0.6 when 3 of 5 samples hit."""
    from evals.metrics.retrieval_eval import evaluate_retrieval

    target = "https://help.example.com/target"
    other = "https://help.example.com/other"

    golden = [
        _make_sample("q1", "Query 1", target),  # hit
        _make_sample("q2", "Query 2", target),  # hit
        _make_sample("q3", "Query 3", target),  # hit
        _make_sample("q4", "Query 4", target),  # miss
        _make_sample("q5", "Query 5", target),  # miss
    ]

    call_count = 0

    async def _retrieve(query: str):
        nonlocal call_count
        call_count += 1
        # First 3 queries return the target URL; last 2 return something else
        if call_count <= 3:
            return [_make_result(target)]
        return [_make_result(other)]

    metrics, _ = await evaluate_retrieval(golden, _retrieve, k=5)

    assert metrics.hit_rate_at_k == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_mrr_first_position():
    """MRR = 1.0 when expected URL is always at position 1."""
    from evals.metrics.retrieval_eval import evaluate_retrieval

    url = "https://help.example.com/article/1"
    golden = [_make_sample("q1", "Query 1", url)]
    retrieve_fn = AsyncMock(return_value=[_make_result(url)])
    metrics, _ = await evaluate_retrieval(golden, retrieve_fn, k=5)

    assert metrics.mrr == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_mrr_second_position():
    """MRR = 0.5 when expected URL is always at position 2."""
    from evals.metrics.retrieval_eval import evaluate_retrieval

    target = "https://help.example.com/target"
    golden = [_make_sample("q1", "Query 1", target)]
    retrieve_fn = AsyncMock(
        return_value=[
            _make_result("https://help.example.com/other", chunk_id="c0"),
            _make_result(target, chunk_id="c1"),
        ]
    )
    metrics, _ = await evaluate_retrieval(golden, retrieve_fn, k=5)

    assert metrics.mrr == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_mrr_no_hits_is_zero():
    """MRR = 0.0 when expected URL is never retrieved."""
    from evals.metrics.retrieval_eval import evaluate_retrieval

    golden = [_make_sample("q1", "Query 1", "https://help.example.com/target")]
    retrieve_fn = AsyncMock(return_value=[_make_result("https://help.example.com/other")])
    metrics, _ = await evaluate_retrieval(golden, retrieve_fn, k=5)

    assert metrics.mrr == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Failure traces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failure_traces_captured_for_misses():
    """Traces for missed queries have status='failure' and produce at least one cluster."""
    from evals.metrics.retrieval_eval import evaluate_retrieval

    target = "https://help.example.com/target"
    other = "https://help.example.com/other"

    golden = [
        _make_sample("q1", "Query hit", target),
        _make_sample("q2", "Query miss", target),
    ]

    call_count = 0

    async def _retrieve(query: str):
        nonlocal call_count
        call_count += 1
        return [_make_result(target if call_count == 1 else other)]

    metrics, clusters = await evaluate_retrieval(golden, _retrieve, k=5)

    assert metrics.hit_rate_at_k == pytest.approx(0.5)
    assert len(clusters) >= 1  # 1 miss → at least one failure cluster


@pytest.mark.asyncio
async def test_no_failures_returns_empty_clusters():
    """FailureClusterer returns empty list when all queries hit."""
    from evals.metrics.retrieval_eval import evaluate_retrieval

    url = "https://help.example.com/article/1"
    golden = [_make_sample("q1", "Query 1", url)]
    retrieve_fn = AsyncMock(return_value=[_make_result(url)])
    _, clusters = await evaluate_retrieval(golden, retrieve_fn, k=5)

    assert clusters == []


# ---------------------------------------------------------------------------
# FailureClusterer grouping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failure_clusterer_groups_by_type():
    """Multiple failures of the same type are grouped in one cluster."""
    from evals.metrics.retrieval_eval import evaluate_retrieval

    target = "https://help.example.com/target"
    other = "https://help.example.com/other"

    golden = [_make_sample(f"q{i}", f"Query {i}", target) for i in range(3)]
    retrieve_fn = AsyncMock(return_value=[_make_result(other)])

    _, clusters = await evaluate_retrieval(golden, retrieve_fn, k=5)

    total_failures = sum(c.count for c in clusters)
    assert total_failures == 3


# ---------------------------------------------------------------------------
# cost gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_retrieval_raises_on_empty_golden():
    """Empty golden list raises ValueError rather than ZeroDivisionError."""
    from evals.metrics.retrieval_eval import evaluate_retrieval

    with pytest.raises(ValueError, match="empty"):
        await evaluate_retrieval([], AsyncMock(), k=5)


def test_answer_eval_raises_without_flag():
    """run_answer_eval raises RuntimeError when CONFIRM_EXPENSIVE_OPS is False."""
    from evals.graders.answer_eval import run_answer_eval

    with pytest.raises(RuntimeError, match="CONFIRM_EXPENSIVE_OPS"):
        run_answer_eval()
