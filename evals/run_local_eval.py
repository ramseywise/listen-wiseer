"""Interactive local retrieval eval — per-query results + aggregate metrics.

Filters to synthetic_da_* samples (the 20 hand-crafted golden queries with
valid corpus references) and pretty-prints hit/miss per query alongside
aggregate hit_rate@k and MRR.

Usage:
    PYTHONPATH=src uv run python -m evals.run_local_eval

    # Override defaults:
    PYTHONPATH=src uv run python -m evals.run_local_eval \\
        --golden data/golden_synthetic_en.jsonl \\
        --k 5 \\
        --filter synthetic_da

Requires:
    - OpenSearch running (make up)
    - Corpus indexed (make ingest-local)
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from retrieval.client import OpenSearchClient, OpenSearchSettings
from retrieval.embedder import EmbedderSettings, MultilingualEmbedder
from schemas.retrieval import RetrievalResult

from evals.metrics.retrieval_eval import evaluate_retrieval
from evals.tasks.models import GoldenSample, RetrievalMetrics
from evals.tasks.tracing import FailureCluster
from utils.logging import configure_logging, get_logger

log = get_logger(__name__)

_GOLDEN_DEFAULT = Path("data/golden_synthetic_en.jsonl")
_FILTER_DEFAULT = "synthetic_da"


def _load_samples(path: Path, prefix_filter: str) -> list[GoldenSample]:
    samples = [
        GoldenSample.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").strip().splitlines()
        if line.strip()
    ]
    if prefix_filter:
        samples = [s for s in samples if s.query_id.startswith(prefix_filter)]
    return samples


def _print_header(n: int, k: int, golden_path: Path) -> None:
    print(f"\n{'=' * 70}")
    print(f"  Retrieval eval  |  n={n}  k={k}  |  {golden_path.name}")
    print(f"{'=' * 70}\n")


def _print_per_query(
    sample: GoldenSample,
    results: list[RetrievalResult],
    k: int,
) -> None:
    urls = [r.chunk.metadata.url for r in results[:k]]
    hit = sample.expected_doc_url in urls if sample.expected_doc_url else None
    rr = (
        next(
            (1 / (i + 1) for i, u in enumerate(urls) if u == sample.expected_doc_url),
            0.0,
        )
        if sample.expected_doc_url
        else None
    )

    # Coverage-gap queries have no expected doc — mark separately
    if not sample.expected_doc_url:
        status = "COVERAGE_GAP"
        rr_str = "n/a"
    else:
        status = "HIT " if hit else "MISS"
        rr_str = f"{rr:.2f}"

    failure_mode = getattr(sample, "failure_mode", "")
    mode_tag = f"[{failure_mode}]" if failure_mode else ""

    print(f"  {status}  rr={rr_str:<4}  {sample.query_id:<22}  {mode_tag}")
    print(f"         query : {sample.query[:80]}")

    if sample.expected_doc_url:
        expected_slug = sample.expected_doc_url.split("/")[-1]
        print(f"         expect: {expected_slug}")
        top_slug = urls[0].split("/")[-1] if urls else "(no results)"
        print(f"         top-1 : {top_slug}")

    if not hit and sample.expected_doc_url and urls:
        # Show where the expected doc landed (if at all)
        try:
            rank = next(i + 1 for i, u in enumerate(urls) if u == sample.expected_doc_url)
            print(
                f"         rank  : {rank} (outside top-{k})"
                if rank > k
                else f"         rank  : {rank}"
            )
        except StopIteration:
            print(f"         rank  : not in top-{k}")
    print()


def _print_summary(metrics: RetrievalMetrics, clusters: list[FailureCluster]) -> None:
    print(f"{'─' * 70}")
    print(f"  hit_rate@{metrics.k:<2}  {metrics.hit_rate_at_k:.3f}")
    print(f"  MRR          {metrics.mrr:.3f}")
    print(f"  n_queries    {metrics.n_queries}")

    if clusters:
        print("\n  Failure clusters:")
        for c in clusters:
            print(f"    {c.failure_type:<25}  n={c.count}")
    print(f"{'=' * 70}\n")


async def run_eval(
    golden_path: Path,
    k: int,
    prefix_filter: str,
) -> None:
    samples = _load_samples(golden_path, prefix_filter)
    if not samples:
        print(f"No samples matched filter '{prefix_filter}' in {golden_path}")
        return

    embedder = MultilingualEmbedder(EmbedderSettings())
    client = OpenSearchClient(OpenSearchSettings())

    # Collect per-query results for pretty-printing alongside aggregate eval
    per_query_results: dict[str, list[RetrievalResult]] = {}

    async def retrieve_fn(query: str) -> list[RetrievalResult]:
        vector = embedder.embed_query(query)
        results = await client.hybrid_search(query_text=query, query_vector=vector, k=k)
        per_query_results[query] = results
        return results

    _print_header(len(samples), k, golden_path)

    metrics, clusters = await evaluate_retrieval(samples, retrieve_fn, k=k)

    for sample in samples:
        results = per_query_results.get(sample.query, [])
        _print_per_query(sample, results, k)

    _print_summary(metrics, clusters)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive local retrieval eval")
    parser.add_argument("--golden", type=Path, default=_GOLDEN_DEFAULT)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--filter",
        default=_FILTER_DEFAULT,
        help="Only eval samples whose query_id starts with this prefix. "
        "Pass '' to run all samples.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    configure_logging()
    args = _parse_args()
    asyncio.run(run_eval(golden_path=args.golden, k=args.k, prefix_filter=args.filter))
