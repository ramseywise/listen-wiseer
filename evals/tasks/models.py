from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class EvalRunConfig(BaseModel):
    """Configuration snapshot for a single evaluation run.

    Logged alongside metrics so results are reproducible and comparable
    across prompt versions, corpus versions, and retrieval settings.
    """

    run_name: str = ""
    prompt_version: str = "v0.1.0"
    model_id: str = "claude-haiku-4-5-20251001"
    eval_dataset: str = ""  # filename or label, e.g. "golden_synthetic_en"
    corpus_version: str = ""  # e.g. "20260327", "first_pancake"
    top_k: int = 5
    notes: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)

    def summary(self) -> dict:
        return self.model_dump(exclude={"timestamp"}) | {"timestamp": self.timestamp.isoformat()}


class GoldenSample(BaseModel):
    query_id: str
    query: str
    expected_doc_url: str
    relevant_chunk_ids: list[str] = []
    category: str = ""
    language: str = "da"
    difficulty: str = "easy"  # easy | medium | hard
    validation_level: str = "silver"  # gold | silver | bronze | synthetic
    source_ticket_id: str = ""


class RetrievalMetrics(BaseModel):
    hit_rate_at_k: float
    mrr: float
    k: int
    n_queries: int


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
