"""CI eval runner — heuristic graders only, no LLM cost.

Loads the golden dataset, runs Tier 1 (intent + routing), compares scores
against the baseline file, and exits non-zero if any metric drops >5%.

Usage:
    PYTHONPATH=src uv run python -m evals.eval_ci

Environment:
    EVAL_BASELINE_PATH   — override default baseline path (optional)
    ANTHROPIC_API_KEY    — not required for CI tier; presence enables full RAGAS
                           (used only by eval-full / make eval-full, not this script)

Exit codes:
    0 — all metrics at or above threshold
    1 — one or more metrics below threshold (regression detected)
    2 — dataset or baseline load error
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from evals.agent.intent_eval import evaluate_intent, evaluate_routing
from evals.run_agent_eval import load_golden_samples
from utils.logging import configure_logging, get_logger

log = get_logger(__name__)

_baseline_env = os.getenv("EVAL_BASELINE_PATH", "")
BASELINE_PATH = (
    Path(_baseline_env)
    if _baseline_env
    else Path(__file__).resolve().parent / "datasets" / "eval_baseline.json"
)
RESULTS_PATH = Path(__file__).resolve().parent / "datasets" / "eval_results.json"

# Minimum tolerated drop before CI fails (5 pp).
REGRESSION_THRESHOLD = 0.05


def load_baseline(path: Path) -> dict[str, float]:
    if not path.exists():
        log.error("eval.ci.baseline_missing", path=str(path))
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("scores", {})


def check_regression(
    baseline: dict[str, float],
    current: dict[str, float],
) -> list[str]:
    """Return a list of failure messages for metrics that regressed beyond threshold."""
    failures: list[str] = []
    for metric, baseline_val in baseline.items():
        current_val = current.get(metric)
        if current_val is None:
            failures.append(
                f"  {metric}: missing from current results (baseline={baseline_val:.3f})"
            )
            continue
        drop = baseline_val - current_val
        if drop > REGRESSION_THRESHOLD:
            failures.append(
                f"  {metric}: {current_val:.3f} vs baseline {baseline_val:.3f} "
                f"(dropped {drop:.3f}, threshold {REGRESSION_THRESHOLD:.3f})"
            )
    return failures


def main() -> int:
    configure_logging()

    samples = load_golden_samples()
    if not samples:
        log.error("eval.ci.no_samples")
        return 2

    # Run heuristic graders (Tier 1 — no LLM calls).
    intent_metrics = evaluate_intent(samples)
    route_metrics = evaluate_routing(samples)

    current_scores: dict[str, float] = {
        "intent_accuracy": intent_metrics.accuracy,
        "route_accuracy": float(route_metrics["route_accuracy"]),
    }

    # Per-intent F1 scores also tracked (useful for spotting per-class drift).
    for intent, f1 in intent_metrics.per_intent_f1.items():
        current_scores[f"f1_{intent}"] = f1

    # Write results for workflow summary / artifact upload.
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps(
            {
                "scores": current_scores,
                "n_samples": intent_metrics.n_samples,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    log.info("eval.ci.results_written", path=str(RESULTS_PATH))

    # Print summary table.
    print(f"\n{'=' * 60}")
    print("  CI Eval — Tier 1 (heuristic, no LLM)")
    print(f"{'=' * 60}")
    print(f"  Samples:         {intent_metrics.n_samples}")
    print(f"  Intent accuracy: {intent_metrics.accuracy:.3f}")
    print(f"  Route accuracy:  {route_metrics['route_accuracy']:.3f}")
    print("\n  Per-intent F1:")
    for intent, f1 in sorted(intent_metrics.per_intent_f1.items()):
        print(f"    {intent:<22} {f1:.3f}")

    # Threshold comparison.
    baseline = load_baseline(BASELINE_PATH)
    if not baseline:
        print("\n  WARNING: no baseline found — writing current scores as new baseline.")
        log.warning("eval.ci.no_baseline", path=str(BASELINE_PATH))
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(
            json.dumps({"scores": current_scores}, indent=2),
            encoding="utf-8",
        )
        print(f"{'=' * 60}\n")
        return 0

    failures = check_regression(baseline, current_scores)

    if failures:
        print("\n  REGRESSION DETECTED (>5% drop from baseline):")
        for msg in failures:
            print(msg)
        print(f"\n{'=' * 60}\n")
        log.error("eval.ci.regression", n_failures=len(failures))
        return 1

    print("\n  All metrics within threshold of baseline.")
    print(f"{'=' * 60}\n")
    log.info("eval.ci.pass", n_metrics=len(current_scores))
    return 0


if __name__ == "__main__":
    sys.exit(main())
