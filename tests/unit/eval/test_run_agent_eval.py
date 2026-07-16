"""Tests for evals/run_agent_eval.py — golden loader + CLI entry point."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from evals.run_agent_eval import (
    GOLDEN_INTENT_PATH,
    load_golden_samples,
    main,
    run_tier1,
)
from evals.tasks.models import AgentGoldenSample


def test_load_golden_samples() -> None:
    """Golden dataset loads and validates with at least 50 samples."""
    samples = load_golden_samples()
    assert len(samples) >= 50
    assert all(isinstance(s, AgentGoldenSample) for s in samples)


def test_load_golden_samples_with_tier_filter() -> None:
    """Tier filter returns only matching samples."""
    tier1 = load_golden_samples(tier_filter=1)
    all_samples = load_golden_samples()
    assert len(tier1) <= len(all_samples)
    assert all(s.eval_tier == 1 for s in tier1)


def test_load_golden_samples_missing_file() -> None:
    """Missing JSONL returns empty list."""
    samples = load_golden_samples(path=Path("/nonexistent/file.jsonl"))
    assert samples == []


def test_golden_path_exists() -> None:
    """The default golden dataset file exists."""
    assert GOLDEN_INTENT_PATH.exists()


def test_tier1_runs_without_cost_gate() -> None:
    """Tier 1 is deterministic — no CONFIRM_EXPENSIVE_OPS needed."""
    samples = load_golden_samples()
    assert len(samples) >= 50
    result = run_tier1(samples)
    assert result is True


def test_main_tier1_returns_zero() -> None:
    """CLI --tier 1 completes successfully."""
    exit_code = main(["--tier", "1"])
    assert exit_code == 0


def test_main_tier2_without_cost_gate_returns_one() -> None:
    """CLI --tier 2 fails without cost gate."""
    with patch.dict("os.environ", {}, clear=False):
        import evals.agent.cost_gate as cg

        # Ensure cost gate is False
        original = cg.CONFIRM_EXPENSIVE_OPS
        cg.CONFIRM_EXPENSIVE_OPS = False
        try:
            exit_code = main(["--tier", "2"])
            assert exit_code == 1
        finally:
            cg.CONFIRM_EXPENSIVE_OPS = original


def test_main_invalid_tier() -> None:
    """CLI rejects invalid --tier values."""
    with pytest.raises(SystemExit):
        main(["--tier", "99"])
