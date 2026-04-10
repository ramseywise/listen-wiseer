"""Eval data models — golden samples, metrics, and run config."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class EvalRunConfig(BaseModel):
    """Configuration snapshot for a single evaluation run.

    Log alongside metrics so results are reproducible and comparable
    across prompt versions, corpus versions, and retrieval settings.
    """

    run_name: str = ""
    prompt_version: str = "v0.1.0"
    model_id: str = "claude-haiku-4-5-20251001"
    eval_dataset: str = ""  # filename or label, e.g. "golden_music_en"
    corpus_version: str = ""  # e.g. "20260410"
    top_k: int = 5
    notes: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)

    def summary(self) -> dict:
        return self.model_dump(exclude={"timestamp"}) | {"timestamp": self.timestamp.isoformat()}


class GoldenSample(BaseModel):
    """A labelled query for retrieval and answer evaluation."""

    query_id: str
    query: str
    expected_doc_url: str
    relevant_chunk_ids: list[str] = []
    category: str = ""  # "artist_info" | "genre_info" | "recommendation" | …
    language: str = "en"
    difficulty: str = "easy"  # easy | medium | hard
    validation_level: str = "silver"  # gold | silver | bronze | synthetic


class RetrievalMetrics(BaseModel):
    hit_rate_at_k: float
    mrr: float
    k: int
    n_queries: int
