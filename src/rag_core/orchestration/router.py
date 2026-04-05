"""Query Router.

Routes queries to the appropriate pipeline based on analysis.

Routing hierarchy:
1. Simple Factual Query → SimplePipeline
2. Procedural/How-to Query → EnhancedPipeline
3. Complex Multi-hop Query → AgenticPipeline
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from orchestration.query_understanding import QueryAnalysis, QueryAnalyzer


class RoutingStrategy(str, Enum):
    """Available routing strategies."""

    SIMPLE = "simple"
    ENHANCED = "enhanced"
    AGENTIC = "agentic"


@dataclass
class RoutingDecision:
    """Result of routing decision."""

    strategy: RoutingStrategy
    confidence: float
    reason: str
    query_analysis: QueryAnalysis | None = None
    metadata: dict[str, Any] | None = None


class QueryRouter:
    """Routes queries to appropriate pipeline.

    Decision flow:
    1. Analyze query (intent, complexity)
    2. Route based on analysis
    """

    SIMPLE_COMPLEXITIES = {"simple"}
    AGENTIC_COMPLEXITIES = {"complex"}

    def __init__(self, query_analyzer: QueryAnalyzer | None = None):
        """Initialize router.

        Args:
            query_analyzer: Query understanding component

        """
        self.query_analyzer = query_analyzer or QueryAnalyzer()

    def route(self, query: str) -> RoutingDecision:
        """Route query to appropriate pipeline.

        Args:
            query: User query

        Returns:
            RoutingDecision with strategy and metadata

        """
        analysis = self.query_analyzer.analyze(query)

        if analysis.complexity in self.AGENTIC_COMPLEXITIES:
            return RoutingDecision(
                strategy=RoutingStrategy.AGENTIC,
                confidence=0.8,
                reason=f"High complexity ({analysis.complexity}) requires iterative retrieval",
                query_analysis=analysis,
                metadata={
                    "complexity": analysis.complexity,
                    "sub_queries": analysis.sub_queries,
                },
            )

        if analysis.complexity in self.SIMPLE_COMPLEXITIES and analysis.intent == "factual":
            return RoutingDecision(
                strategy=RoutingStrategy.SIMPLE,
                confidence=0.85,
                reason="Simple factual query",
                query_analysis=analysis,
                metadata={"intent": analysis.intent, "complexity": analysis.complexity},
            )

        return RoutingDecision(
            strategy=RoutingStrategy.ENHANCED,
            confidence=0.75,
            reason=f"Query type '{analysis.intent}' benefits from enhanced pipeline",
            query_analysis=analysis,
            metadata={
                "intent": analysis.intent,
                "complexity": analysis.complexity,
                "has_entities": bool(analysis.entities),
            },
        )

    def get_stats(self) -> dict[str, Any]:
        """Get routing statistics (for monitoring)."""
        # TODO(3): Implement routing stats tracking
        return {
            "total_routed": 0,
            "by_strategy": {
                "simple": 0,
                "enhanced": 0,
                "agentic": 0,
            },
        }
