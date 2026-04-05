"""Retrieval evaluation harness.

Computes hit_rate@k and MRR over a golden dataset, traces each query,
and clusters failures with FailureClusterer.

CLI: python -m eval.retrieval_eval --golden data/golden_silver.jsonl
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from schemas.retrieval import RetrievalResult

from evals.tasks.models import GoldenSample, RetrievalMetrics
from evals.tasks.tracing import FailureCluster, FailureClusterer, PipelineTracer
from utils.logging import get_logger

log = get_logger(__name__)

RetrieveFn = Callable[[str], Coroutine[Any, Any, list[RetrievalResult]]]


def _log_langfuse_scores(metrics: RetrievalMetrics, trace_id: str) -> None:
    """Log retrieval metrics as LangFuse scores.  No-op if LangFuse is unconfigured."""
    try:
        from langfuse import Langfuse

        lf = Langfuse()
        lf.create_score(trace_id=trace_id, name="hit_rate_at_k", value=metrics.hit_rate_at_k)
        lf.create_score(trace_id=trace_id, name="mrr", value=metrics.mrr)
        log.info("eval.langfuse.scores.logged", trace_id=trace_id)
    except Exception as exc:
        log.warning("eval.langfuse.scores.failed", error=str(exc))


async def evaluate_retrieval(
    golden: list[GoldenSample],
    retrieve_fn: RetrieveFn,
    k: int = 5,
    langfuse_trace_id: str | None = None,
) -> tuple[RetrievalMetrics, list[FailureCluster]]:
    """Evaluate retrieval quality against a golden dataset.

    Args:
        golden:      List of golden samples (query + expected_doc_url).
        retrieve_fn: Async callable ``(query: str) -> list[RetrievalResult]``.
        k:           Cutoff for hit-rate and MRR calculation.

    Returns:
        Tuple of (RetrievalMetrics, list[FailureCluster]).
    """
    if not golden:
        raise ValueError("golden dataset is empty — nothing to evaluate")

    tracer = PipelineTracer()
    hits: list[int] = []
    reciprocal_ranks: list[float] = []

    for sample in golden:
        trace = tracer.create_trace(sample.query_id, sample.query)
        results = await retrieve_fn(sample.query)

        urls = [r.chunk.metadata.url for r in results[:k]]

        hit = sample.expected_doc_url in urls
        hits.append(int(hit))

        rr = next(
            (1 / (i + 1) for i, u in enumerate(urls) if u == sample.expected_doc_url),
            0.0,
        )
        reciprocal_ranks.append(rr)

        trace.retrieval_confidence = max((r.score for r in results[:k]), default=0.0)
        trace.status = "success" if hit else "failure"
        trace.failure_reason = None if hit else "expected_doc_not_in_top_k"

    clusterer = FailureClusterer()
    clusters = clusterer.cluster_failures(tracer.get_failure_traces())

    n = len(golden)
    metrics = RetrievalMetrics(
        hit_rate_at_k=sum(hits) / n,
        mrr=sum(reciprocal_ranks) / n,
        k=k,
        n_queries=n,
    )
    log.info("eval.retrieval.done", **metrics.model_dump())
    log.info("eval.failure_clusters", clusters=clusterer.get_summary())
    if langfuse_trace_id:
        _log_langfuse_scores(metrics, langfuse_trace_id)
    return metrics, clusters


def _main() -> None:
    import argparse
    import asyncio
    import json
    from pathlib import Path

    from retrieval.client import OpenSearchClient, OpenSearchSettings
    from retrieval.embedder import EmbedderSettings, MultilingualEmbedder

    from utils.logging import configure_logging

    configure_logging()

    parser = argparse.ArgumentParser(description="Run retrieval eval against golden dataset")
    parser.add_argument("--golden", type=Path, required=True, help="Golden JSONL path")
    parser.add_argument("--k", type=int, default=5, help="Top-k cutoff (default: 5)")
    args = parser.parse_args()

    samples = [
        GoldenSample.model_validate(json.loads(line))
        for line in args.golden.read_text().strip().splitlines()
        if line.strip()
    ]

    embedder = MultilingualEmbedder(EmbedderSettings())
    client = OpenSearchClient(OpenSearchSettings())
    k = args.k

    async def retrieve_fn(query: str) -> list[RetrievalResult]:
        vector = embedder.embed_query(query)
        return await client.hybrid_search(query_text=query, query_vector=vector, k=k)

    asyncio.run(evaluate_retrieval(samples, retrieve_fn, k=k))


if __name__ == "__main__":
    _main()
