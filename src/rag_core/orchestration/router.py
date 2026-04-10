"""Query Router — music-domain routing decisions.

Routes queries to the appropriate knowledge base and retrieval strategy.

Routing hierarchy:
    artist_db   → artist biography / discography knowledge (Wikipedia, biographies)
    genre_db    → genre explanation / history knowledge
    history     → user's personal listening history (Spotify data)
    snippet     → fast FTS bypass for simple factual lookups
    direct      → no retrieval needed (chit_chat, out_of_scope)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from orchestration.query_understanding import QueryAnalysis, QueryAnalyzer


class RoutingStrategy(StrEnum):
    ARTIST_DB = "artist_db"  # artist info → Wikipedia / biography corpus
    GENRE_DB = "genre_db"  # genre info → genre guide corpus
    HISTORY = "history"  # personal history → Spotify listening data
    SNIPPET = "snippet"  # fast FTS bypass for simple factual lookups
    DIRECT = "direct"  # no retrieval (chit_chat, out_of_scope)


@dataclass
class RoutingDecision:
    strategy: RoutingStrategy
    retrieval_mode: str  # "dense" | "hybrid" | "snippet"
    confidence: float
    reason: str
    query_analysis: QueryAnalysis | None = None


_INTENT_TO_STRATEGY: dict[str, RoutingStrategy] = {
    "artist_info": RoutingStrategy.ARTIST_DB,
    "genre_info": RoutingStrategy.GENRE_DB,
    "recommendation": RoutingStrategy.ARTIST_DB,  # recommendations pull artist/genre context
    "history": RoutingStrategy.HISTORY,
    "chit_chat": RoutingStrategy.DIRECT,
    "out_of_scope": RoutingStrategy.DIRECT,
}


class QueryRouter:
    """Routes queries to music knowledge bases and retrieval modes.

    Decision flow:
        1. Analyze query (intent, complexity, retrieval_mode)
        2. Map intent → strategy
        3. If retrieval_mode==snippet AND strategy is a DB → promote to SNIPPET
    """

    def __init__(self, query_analyzer: QueryAnalyzer | None = None) -> None:
        self._analyzer = query_analyzer or QueryAnalyzer()

    def route(self, query: str) -> RoutingDecision:
        """Route *query* and return a RoutingDecision.

        Args:
            query: Raw user query string.

        Returns:
            RoutingDecision with strategy, retrieval_mode, confidence, and reason.
        """
        analysis = self._analyzer.analyze(query)
        strategy = _INTENT_TO_STRATEGY.get(analysis.intent, RoutingStrategy.ARTIST_DB)

        # Promote simple factual DB lookups to fast snippet path
        if analysis.retrieval_mode == "snippet" and strategy in (
            RoutingStrategy.ARTIST_DB,
            RoutingStrategy.GENRE_DB,
        ):
            strategy = RoutingStrategy.SNIPPET

        reason = (
            f"intent={analysis.intent} complexity={analysis.complexity} "
            f"retrieval_mode={analysis.retrieval_mode}"
        )
        return RoutingDecision(
            strategy=strategy,
            retrieval_mode=analysis.retrieval_mode,
            confidence=analysis.confidence,
            reason=reason,
            query_analysis=analysis,
        )
