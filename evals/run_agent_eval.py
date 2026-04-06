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
    """Tier 2: trajectory eval. Requires CONFIRM_EXPENSIVE_OPS=true."""
    from evals.agent.cost_gate import CONFIRM_EXPENSIVE_OPS

    if not CONFIRM_EXPENSIVE_OPS:
        log.error("eval.tier2.cost_gate", msg="Set CONFIRM_EXPENSIVE_OPS=true")
        print("ERROR: Tier 2 requires CONFIRM_EXPENSIVE_OPS=true (LLM calls).")
        return False

    log.info("eval.tier2.start", n_samples=len(samples))
    print("\nTier 2 — Trajectory eval: not yet wired to live graph (Phase 6).")
    return True


def run_tier3(samples: list[AgentGoldenSample]) -> bool:
    """Tier 3: RAGAS + DeepEval e2e graders. Requires CONFIRM_EXPENSIVE_OPS=true."""
    from evals.agent.cost_gate import CONFIRM_EXPENSIVE_OPS

    if not CONFIRM_EXPENSIVE_OPS:
        log.error("eval.tier3.cost_gate", msg="Set CONFIRM_EXPENSIVE_OPS=true")
        print("ERROR: Tier 3 requires CONFIRM_EXPENSIVE_OPS=true (LLM calls).")
        return False

    log.info("eval.tier3.start", n_samples=len(samples))
    print("\nTier 3 — RAGAS + DeepEval e2e graders: not yet wired to live graph (Phase 6).")
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
