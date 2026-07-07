from __future__ import annotations

from pydantic import BaseModel


class AgentGoldenSample(BaseModel):
    """Golden sample for agent eval — intent, routing, and tool selection."""

    sample_id: str
    query: str
    expected_intent: str
    expected_confidence_min: float = 0.0
    expected_tools: list[str] = []
    expected_entities: dict[str, list[str]] = {}
    expected_route: str = "rewrite_query"  # or "clarify_or_proceed"
    difficulty: str = "easy"
    eval_tier: int = 1  # 1=unit, 2=trajectory, 3=e2e
    notes: str = ""


class IntentEvalMetrics(BaseModel):
    """Aggregate intent classification eval results."""

    accuracy: float
    per_intent_f1: dict[str, float]
    confusion: dict[str, dict[str, int]]
    n_samples: int
    confidence_threshold: float
