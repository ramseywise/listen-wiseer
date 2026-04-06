from __future__ import annotations

import importlib

import pytest


def test_cost_gate_default_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONFIRM_EXPENSIVE_OPS", raising=False)
    import evals.agent.cost_gate as cg

    importlib.reload(cg)
    assert cg.CONFIRM_EXPENSIVE_OPS is False


def test_cost_gate_true_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFIRM_EXPENSIVE_OPS", "true")
    import evals.agent.cost_gate as cg

    importlib.reload(cg)
    assert cg.CONFIRM_EXPENSIVE_OPS is True


def test_cost_gate_true_with_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFIRM_EXPENSIVE_OPS", "1")
    import evals.agent.cost_gate as cg

    importlib.reload(cg)
    assert cg.CONFIRM_EXPENSIVE_OPS is True


def test_cost_gate_false_with_random_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFIRM_EXPENSIVE_OPS", "yes")
    import evals.agent.cost_gate as cg

    importlib.reload(cg)
    assert cg.CONFIRM_EXPENSIVE_OPS is False
