"""Listen-wiseer agent eval harness.

Three-tier eval with a hand-crafted music-domain golden dataset.

Usage:
    # Tier 1 — deterministic intent/route eval (free, CI-safe):
    PYTHONPATH=src uv run python -m evals.run_agent_eval --tier 1

    # Tier 2 — trajectory eval with LangFuse (costs money):
    CONFIRM_EXPENSIVE_OPS=true PYTHONPATH=src uv run python -m evals.run_agent_eval --tier 2

    # Tier 3 — e2e with RAGAS + DeepEval graders (costs money):
    CONFIRM_EXPENSIVE_OPS=true PYTHONPATH=src uv run python -m evals.run_agent_eval --tier 3

    # All tiers:
    CONFIRM_EXPENSIVE_OPS=true PYTHONPATH=src uv run python -m evals.run_agent_eval --tier all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evals.agent.intent_eval import evaluate_intent, evaluate_routing
from evals.tasks.models import AgentGoldenSample
from utils.logging import configure_logging, get_logger

log = get_logger(__name__)

GOLDEN_INTENT_PATH = Path(__file__).resolve().parent / "datasets" / "golden_intent.jsonl"

VALID_TIERS = {"1", "2", "3", "all"}


def load_golden_samples(
    path: Path | None = None,
    tier_filter: int | None = None,
) -> list[AgentGoldenSample]:
    """Load and validate golden samples from JSONL.

    Args:
        path: Path to the JSONL file. Defaults to golden_intent.jsonl.
        tier_filter: If set, only return samples matching this eval_tier.

    Returns:
        List of validated AgentGoldenSample.
    """
    target = path or GOLDEN_INTENT_PATH
    if not target.exists():
        log.error("eval.golden.not_found", path=str(target))
        return []

    samples = [
        AgentGoldenSample.model_validate(json.loads(line))
        for line in target.read_text(encoding="utf-8").strip().splitlines()
        if line.strip()
    ]

    if tier_filter is not None:
        samples = [s for s in samples if s.eval_tier == tier_filter]

    log.info("eval.golden.loaded", n_samples=len(samples), tier_filter=tier_filter)
    return samples


def run_tier1(samples: list[AgentGoldenSample]) -> bool:
    """Tier 1: deterministic intent + route eval. No LLM calls."""
    log.info("eval.tier1.start", n_samples=len(samples))

    intent_metrics = evaluate_intent(samples)
    route_metrics = evaluate_routing(samples)

    print(f"\n{'=' * 60}")
    print("  Tier 1 — Intent Classification + Routing")
    print(f"{'=' * 60}")
    print(f"  Samples:    {intent_metrics.n_samples}")
    print(f"  Accuracy:   {intent_metrics.accuracy:.3f}")
    print(f"  Threshold:  {intent_metrics.confidence_threshold}")
    print(f"\n  Per-intent F1:")
    for intent, f1 in sorted(intent_metrics.per_intent_f1.items()):
        print(f"    {intent:<20} {f1:.3f}")

    print(f"\n  Confusion matrix:")
    all_intents = sorted(intent_metrics.per_intent_f1.keys())
    header = "  " + " " * 22 + "  ".join(f"{i[:6]:>6}" for i in all_intents)
    print(header)
    for expected in all_intents:
        row = intent_metrics.confusion.get(expected, {})
        counts = "  ".join(f"{row.get(p, 0):>6}" for p in all_intents)
        print(f"  {expected:<20} {counts}")

    print(f"\n  Route accuracy: {route_metrics['route_accuracy']:.3f}")
    print(f"{'=' * 60}\n")

    log.info(
        "eval.tier1.complete",
        accuracy=intent_metrics.accuracy,
        route_accuracy=route_metrics["route_accuracy"],
    )
    return True


def run_tier2(samples: list[AgentGoldenSample]) -> bool:
    """Tier 2: trajectory eval against live graph. Requires CONFIRM_EXPENSIVE_OPS=true."""
    import asyncio

    from evals.agent.cost_gate import CONFIRM_EXPENSIVE_OPS
    from evals.agent.trajectory_eval import TrajectoryResult, evaluate_trajectory

    if not CONFIRM_EXPENSIVE_OPS:
        log.error("eval.tier2.cost_gate", msg="Set CONFIRM_EXPENSIVE_OPS=true")
        print("ERROR: Tier 2 requires CONFIRM_EXPENSIVE_OPS=true (LLM calls).")
        return False

    from agent.graph import build_graph
    from langgraph.checkpoint.memory import MemorySaver

    graph = build_graph(checkpointer=MemorySaver())

    log.info("eval.tier2.start", n_samples=len(samples))
    results: list[TrajectoryResult] = asyncio.run(
        evaluate_trajectory(samples, graph, enable_tracing=True)
    )

    n = len(results)
    n_intent = sum(1 for r in results if r.intent_match)
    n_tool = sum(1 for r in results if r.tool_match)

    print(f"\n{'=' * 60}")
    print("  Tier 2 — Trajectory Eval")
    print(f"{'=' * 60}")
    print(f"  Samples:         {n}")
    print(f"  Intent accuracy: {n_intent / n:.3f}")
    print(f"  Tool accuracy:   {n_tool / n:.3f}")
    print(f"\n  Per-sample breakdown:")
    for r in results:
        intent_ok = "✓" if r.intent_match else "✗"
        tool_ok = "✓" if r.tool_match else "✗"
        print(f"    [{intent_ok} intent] [{tool_ok} tools]  {r.sample_id}: {r.query[:60]}")
    print(f"{'=' * 60}\n")

    log.info(
        "eval.tier2.complete",
        n_samples=n,
        intent_accuracy=n_intent / n,
        tool_accuracy=n_tool / n,
    )
    return True


def run_tier3(samples: list[AgentGoldenSample]) -> bool:
    """Tier 3: RAGAS faithfulness + tool correctness against live graph. Requires CONFIRM_EXPENSIVE_OPS=true."""
    import asyncio

    from evals.agent.cost_gate import CONFIRM_EXPENSIVE_OPS
    from evals.agent.graders import grade_faithfulness, grade_tool_correctness
    from evals.agent.trajectory_eval import evaluate_trajectory

    if not CONFIRM_EXPENSIVE_OPS:
        log.error("eval.tier3.cost_gate", msg="Set CONFIRM_EXPENSIVE_OPS=true")
        print("ERROR: Tier 3 requires CONFIRM_EXPENSIVE_OPS=true (LLM calls).")
        return False

    from agent.graph import build_graph
    from langgraph.checkpoint.memory import MemorySaver

    graph = build_graph(checkpointer=MemorySaver())

    log.info("eval.tier3.start", n_samples=len(samples))
    traj_results = asyncio.run(evaluate_trajectory(samples, graph, enable_tracing=True))

    # Build a map for quick lookup of trajectory results
    traj_map = {r.sample_id: r for r in traj_results}
    sample_map = {s.sample_id: s for s in samples}

    faithfulness_scores: list[float] = []
    tool_scores: list[float] = []

    print(f"\n{'=' * 60}")
    print("  Tier 3 — RAGAS + Tool Correctness")
    print(f"{'=' * 60}")

    for r in traj_results:
        sample = sample_map[r.sample_id]

        # Tool correctness is deterministic — always run
        tool_score = grade_tool_correctness(r.query, sample.expected_tools, r.tools_called)
        tool_scores.append(tool_score)

        # RAGAS faithfulness — only meaningful when the agent produced a response
        # and called tools (tool names used as minimal context proxy)
        faith_score = 0.0
        if r.final_response and r.tools_called:
            faith_score = grade_faithfulness(
                question=r.query,
                answer=r.final_response,
                contexts=r.tools_called,
            )
        faithfulness_scores.append(faith_score)

        print(
            f"    {r.sample_id}: tool={tool_score:.2f}  faith={faith_score:.2f}  {r.query[:50]}"
        )

    avg_tool = sum(tool_scores) / len(tool_scores) if tool_scores else 0.0
    avg_faith = sum(faithfulness_scores) / len(faithfulness_scores) if faithfulness_scores else 0.0

    print(f"\n  Avg tool correctness: {avg_tool:.3f}")
    print(f"  Avg faithfulness:     {avg_faith:.3f}")
    print(f"{'=' * 60}\n")

    log.info(
        "eval.tier3.complete",
        n_samples=len(traj_results),
        avg_tool_correctness=avg_tool,
        avg_faithfulness=avg_faith,
    )
    return True


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Listen-wiseer agent eval harness")
    parser.add_argument(
        "--tier",
        type=str,
        default="1",
        choices=sorted(VALID_TIERS),
        help="Eval tier: 1 (deterministic), 2 (trajectory), 3 (e2e), all",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 on success, 1 on failure."""
    configure_logging()
    args = _parse_args(argv)
    tier = args.tier

    samples = load_golden_samples()
    if not samples:
        log.error("eval.main.no_samples")
        return 1

    success = True

    if tier in ("1", "all"):
        success = run_tier1(samples) and success

    if tier in ("2", "all"):
        tier2_samples = [s for s in samples if s.eval_tier <= 2]
        success = run_tier2(tier2_samples) and success

    if tier in ("3", "all"):
        success = run_tier3(samples) and success

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
