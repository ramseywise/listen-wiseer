"""Pipeline tracing and failure clustering for RAG observability.

Level 2 of evaluation framework: Attribution & Debugging
- Track each step of the RAG pipeline
- Cluster failures to identify systematic issues
- Attribute answer claims to source chunks
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Any

# =============================================================================
# PIPELINE TRACE
# =============================================================================


@dataclass
class SpanInfo:
    """Information about a single pipeline span (step)."""

    name: str
    start_time: datetime
    end_time: datetime | None = None
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "success"  # success, error, warning
    error_message: str | None = None


@dataclass
class RetrievalSpan(SpanInfo):
    """Retrieval step trace."""

    query: str = ""
    num_retrieved: int = 0
    top_scores: list[float] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    retrieval_method: str = ""  # dense, sparse, hybrid


@dataclass
class GenerationSpan(SpanInfo):
    """Generation step trace."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    temperature: float = 0.0


@dataclass
class PipelineTrace:
    """Complete trace of a RAG pipeline execution."""

    trace_id: str
    query_id: str
    query: str
    timestamp: datetime = field(default_factory=datetime.now)

    # Pipeline spans
    retrieval: RetrievalSpan | None = None
    reranking: SpanInfo | None = None
    generation: GenerationSpan | None = None

    # Results
    answer: str = ""
    retrieved_chunks: list[dict] = field(default_factory=list)

    # Attribution
    chunk_attributions: dict[str, list[str]] = field(default_factory=dict)

    # Quality signals
    retrieval_confidence: float = 0.0
    generation_confidence: float = 0.0

    # Outcome
    status: str = "success"  # success, partial, failure
    failure_reason: str | None = None

    @property
    def total_latency_ms(self) -> float:
        """Total pipeline latency."""
        total = 0.0
        if self.retrieval:
            total += self.retrieval.latency_ms
        if self.reranking:
            total += self.reranking.latency_ms
        if self.generation:
            total += self.generation.latency_ms
        return total

    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        if self.generation:
            return self.generation.total_tokens
        return 0

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
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
            "generation_confidence": self.generation_confidence,
            "answer_length": len(self.answer),
            "num_chunks": len(self.retrieved_chunks),
        }


class PipelineTracer:
    """Trace RAG pipeline execution."""

    def __init__(self) -> None:
        self.traces: list[PipelineTrace] = []

    def create_trace(self, query_id: str, query: str) -> PipelineTrace:
        """Create a new trace for a query."""
        trace_id = sha256(f"{query_id}:{datetime.now().isoformat()}".encode()).hexdigest()[:16]
        trace = PipelineTrace(
            trace_id=trace_id,
            query_id=query_id,
            query=query,
        )
        self.traces.append(trace)
        return trace

    def get_traces(self, status: str | None = None) -> list[PipelineTrace]:
        """Get traces, optionally filtered by status."""
        if status:
            return [t for t in self.traces if t.status == status]
        return self.traces

    def get_failure_traces(self) -> list[PipelineTrace]:
        """Get all failed traces."""
        return [t for t in self.traces if t.status == "failure"]

    def export_traces(self, path: str) -> None:
        """Export traces to JSON file."""
        data = [t.to_dict() for t in self.traces]
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


# =============================================================================
# FAILURE CLUSTERING
# =============================================================================


@dataclass
class FailureCluster:
    """A cluster of similar failures."""

    cluster_id: str
    failure_type: str
    count: int
    examples: list[PipelineTrace]
    common_patterns: list[str]
    suggested_fix: str


class FailureClusterer:
    """Cluster failures to identify systematic issues."""

    FAILURE_TYPES = {
        "retrieval_failure": "Wrong documents retrieved - query-document mismatch",
        "ranking_failure": "Right docs found but buried in results",
        "generation_failure": "Right docs, wrong answer - model didn't use context",
        "grounding_failure": "Answer contains unsupported claims (hallucination)",
        "coverage_gap": "Topic not in knowledge base",
        "complexity_failure": "Question too complex for single retrieval",
        "zero_retrieval": "No relevant chunks retrieved",
        "low_confidence": "Low retrieval confidence",
        "context_noise": "Too much irrelevant context",
        "timeout": "Pipeline timeout",
        "unknown": "Unknown failure type",
    }

    def __init__(self, embedder: Callable | None = None) -> None:
        self.embedder = embedder
        self.clusters: list[FailureCluster] = []

    def classify_failure(self, trace: PipelineTrace) -> str:
        """Classify a single failure into a type."""
        if trace.status != "failure":
            return "success"

        if trace.retrieval and trace.retrieval.num_retrieved == 0:
            return "coverage_gap"

        if trace.retrieval_confidence < 0.3:
            return "retrieval_failure"

        if trace.retrieval_confidence < 0.5 and trace.generation:
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
            if "incomplete" in reason:
                return "generation_failure"
            if "noise" in reason:
                return "context_noise"

        return "unknown"

    def cluster_failures(self, traces: list[PipelineTrace]) -> list[FailureCluster]:
        """Cluster failures by type and similarity."""
        failures = [t for t in traces if t.status == "failure"]

        if not failures:
            return []

        type_groups: dict[str, list[PipelineTrace]] = defaultdict(list)
        for trace in failures:
            failure_type = self.classify_failure(trace)
            type_groups[failure_type].append(trace)

        clusters = []
        for failure_type, group_traces in type_groups.items():
            common_patterns = self._find_common_patterns([t.query for t in group_traces])
            cluster = FailureCluster(
                cluster_id=f"{failure_type}_{len(group_traces)}",
                failure_type=failure_type,
                count=len(group_traces),
                examples=group_traces[:5],
                common_patterns=common_patterns,
                suggested_fix=self._suggest_fix(failure_type),
            )
            clusters.append(cluster)

        self.clusters = sorted(clusters, key=lambda x: x.count, reverse=True)
        return self.clusters

    def _find_common_patterns(self, queries: list[str]) -> list[str]:
        """Find common patterns in failed queries."""
        patterns = []

        lengths = [len(q.split()) for q in queries]
        avg_length = statistics.mean(lengths) if lengths else 0
        if avg_length > 20:
            patterns.append("Long/complex queries")
        elif avg_length < 5:
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

    def _suggest_fix(self, failure_type: str) -> str:
        """Suggest fixes for failure types."""
        suggestions = {
            "retrieval_failure": "Improve embeddings, add query expansion, check synonyms",
            "ranking_failure": "Tune reranker, adjust fusion weights, check relevance scoring",
            "generation_failure": "Improve prompt template, add few-shot examples",
            "grounding_failure": "Strengthen attribution instructions, enable claim verification",
            "coverage_gap": "Expand corpus with missing content, check content pipeline",
            "complexity_failure": "Route to iterative retrieval, implement query decomposition",
            "zero_retrieval": "Expand query terms, check index coverage, lower similarity threshold",
            "low_confidence": "Add more domain-specific content, tune retrieval parameters",
            "context_noise": "Add reranking, reduce top-k, improve chunk quality",
            "timeout": "Optimize retrieval, add caching, reduce context size",
            "unknown": "Review trace details, add more failure classification rules",
        }
        return suggestions.get(failure_type, "Review trace details")

    def get_summary(self) -> dict:
        """Get summary of failure clusters."""
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
