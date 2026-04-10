"""Pipeline tracing and failure clustering for RAG observability."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Any


@dataclass
class SpanInfo:
    name: str
    start_time: datetime
    end_time: datetime | None = None
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "success"
    error_message: str | None = None


@dataclass
class RetrievalSpan(SpanInfo):
    query: str = ""
    num_retrieved: int = 0
    top_scores: list[float] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    retrieval_method: str = ""  # dense | hybrid | snippet


@dataclass
class GenerationSpan(SpanInfo):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""


@dataclass
class PipelineTrace:
    trace_id: str
    query_id: str
    query: str
    timestamp: datetime = field(default_factory=datetime.now)

    retrieval: RetrievalSpan | None = None
    reranking: SpanInfo | None = None
    generation: GenerationSpan | None = None

    answer: str = ""
    retrieved_chunks: list[dict] = field(default_factory=list)
    chunk_attributions: dict[str, list[str]] = field(default_factory=dict)

    retrieval_confidence: float = 0.0
    generation_confidence: float = 0.0

    status: str = "success"
    failure_reason: str | None = None

    @property
    def total_latency_ms(self) -> float:
        total = 0.0
        for span in (self.retrieval, self.reranking, self.generation):
            if span:
                total += span.latency_ms
        return total

    @property
    def total_tokens(self) -> int:
        return self.generation.total_tokens if self.generation else 0

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "query_id": self.query_id,
            "query": self.query,
            "timestamp": self.timestamp.isoformat(),
            "total_latency_ms": self.total_latency_ms,
            "total_tokens": self.total_tokens,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "retrieval_confidence": self.retrieval_confidence,
            "answer_length": len(self.answer),
            "num_chunks": len(self.retrieved_chunks),
        }


class PipelineTracer:
    def __init__(self) -> None:
        self.traces: list[PipelineTrace] = []

    def create_trace(self, query_id: str, query: str) -> PipelineTrace:
        trace_id = sha256(f"{query_id}:{datetime.now().isoformat()}".encode()).hexdigest()[:16]
        trace = PipelineTrace(trace_id=trace_id, query_id=query_id, query=query)
        self.traces.append(trace)
        return trace

    def get_traces(self, status: str | None = None) -> list[PipelineTrace]:
        if status:
            return [t for t in self.traces if t.status == status]
        return self.traces

    def get_failure_traces(self) -> list[PipelineTrace]:
        return [t for t in self.traces if t.status == "failure"]

    def export_traces(self, path: str) -> None:
        with open(path, "w") as fh:
            json.dump([t.to_dict() for t in self.traces], fh, indent=2)


@dataclass
class FailureCluster:
    cluster_id: str
    failure_type: str
    count: int
    examples: list[PipelineTrace]
    common_patterns: list[str]
    suggested_fix: str


class FailureClusterer:
    """Cluster pipeline failures to identify systematic issues."""

    FAILURE_TYPES = {
        "retrieval_failure": "Wrong documents retrieved — query-document mismatch",
        "ranking_failure": "Right docs found but buried in results",
        "generation_failure": "Right docs, wrong answer — model didn't use context",
        "grounding_failure": "Answer contains unsupported claims (hallucination)",
        "coverage_gap": "Topic not in knowledge base",
        "complexity_failure": "Question too complex for single retrieval",
        "zero_retrieval": "No relevant chunks retrieved",
        "low_confidence": "Low retrieval confidence",
        "context_noise": "Too much irrelevant context",
        "timeout": "Pipeline timeout",
        "unknown": "Unknown failure type",
    }

    _FIXES = {
        "retrieval_failure": "Improve embeddings, add query expansion, check synonyms",
        "ranking_failure": "Tune reranker, adjust fusion weights",
        "generation_failure": "Improve prompt template, add few-shot examples",
        "grounding_failure": "Strengthen attribution instructions",
        "coverage_gap": "Expand corpus — add missing artists or genres",
        "complexity_failure": "Route to iterative retrieval, implement query decomposition",
        "zero_retrieval": "Expand query terms, check index coverage",
        "low_confidence": "Add more domain content, tune retrieval parameters",
        "context_noise": "Add reranking, reduce top-k, improve chunk quality",
        "timeout": "Optimize retrieval, add caching",
        "unknown": "Review trace details",
    }

    def __init__(self) -> None:
        self.clusters: list[FailureCluster] = []

    def classify_failure(self, trace: PipelineTrace) -> str:
        if trace.status != "failure":
            return "success"
        if trace.retrieval and trace.retrieval.num_retrieved == 0:
            return "coverage_gap"
        if trace.retrieval_confidence < 0.3:
            return "retrieval_failure"
        if trace.retrieval_confidence < 0.5:
            return "ranking_failure"
        if trace.generation and trace.generation.status == "error":
            return "generation_failure"
        if trace.failure_reason:
            reason = trace.failure_reason.lower()
            if "timeout" in reason:
                return "timeout"
            if "hallucin" in reason or "unsupported" in reason:
                return "grounding_failure"
            if "complex" in reason or "multi-hop" in reason:
                return "complexity_failure"
            if "noise" in reason:
                return "context_noise"
        return "unknown"

    def cluster_failures(self, traces: list[PipelineTrace]) -> list[FailureCluster]:
        failures = [t for t in traces if t.status == "failure"]
        if not failures:
            return []

        type_groups: dict[str, list[PipelineTrace]] = defaultdict(list)
        for trace in failures:
            type_groups[self.classify_failure(trace)].append(trace)

        self.clusters = sorted(
            [
                FailureCluster(
                    cluster_id=f"{ft}_{len(group)}",
                    failure_type=ft,
                    count=len(group),
                    examples=group[:5],
                    common_patterns=self._find_common_patterns([t.query for t in group]),
                    suggested_fix=self._FIXES.get(ft, "Review trace details"),
                )
                for ft, group in type_groups.items()
            ],
            key=lambda c: c.count,
            reverse=True,
        )
        return self.clusters

    def _find_common_patterns(self, queries: list[str]) -> list[str]:
        patterns: list[str] = []
        if not queries:
            return patterns

        lengths = [len(q.split()) for q in queries]
        avg_len = statistics.mean(lengths)
        if avg_len > 20:
            patterns.append("Long/complex queries")
        elif avg_len < 5:
            patterns.append("Very short queries")

        all_words = " ".join(queries).lower().split()
        word_counts: dict[str, int] = defaultdict(int)
        for word in all_words:
            if len(word) > 4:
                word_counts[word] += 1

        total = len(queries)
        for word, count in sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
            if count / total > 0.3:
                patterns.append(f"Contains '{word}'")

        return patterns[:5]

    def get_summary(self) -> dict:
        return {
            "total_clusters": len(self.clusters),
            "clusters": [
                {
                    "type": c.failure_type,
                    "count": c.count,
                    "patterns": c.common_patterns,
                    "fix": c.suggested_fix,
                }
                for c in self.clusters
            ],
        }
