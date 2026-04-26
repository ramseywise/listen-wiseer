"""Query understanding layer for pre-retrieval analysis.

Components:
- Intent classification (music domain)
- Query expansion (music synonyms)
- Entity extraction (mood, time period, context)
- Query decomposition (multi-hop)
- Retrieval mode selection (dense | hybrid | snippet)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from utils.logging import get_logger

log = get_logger(__name__)


# =============================================================================
# QUERY ANALYSIS RESULT
# =============================================================================


@dataclass
class QueryAnalysis:
    """Result of query analysis."""

    original_query: str
    intent: str  # artist_info | genre_info | recommendation | history | explore_my_taste | discover | chit_chat
    complexity: str  # simple | moderate | complex
    expanded_query: str
    entities: dict[str, list[str]]
    sub_queries: list[str]
    retrieval_mode: str  # dense | hybrid | snippet
    confidence: float


# =============================================================================
# INTENT CLASSIFICATION
# =============================================================================

INTENT_PATTERNS: dict[str, list[str]] = {
    "artist_info": [
        "who is",
        "tell me about",
        "what do you know about",
        "biography",
        "history of",
        "background on",
        "artist info",
        "about the band",
        "when did",
        "where is",
        "discography",
        "influences",
        "style of",
    ],
    "genre_info": [
        "what is",
        "explain",
        "describe",
        "genre",
        "subgenre",
        "music style",
        "what does",
        "characteristics of",
        "origins of",
    ],
    "recommendation": [
        "recommend",
        "suggest",
        "find me",
        "similar to",
        "sounds like",
        "more of",
        "playlist",
        "tracks like",
        "what should i listen to",
        "based on",
        "fans of",
        "if i like",
        "like",
    ],
    "history": [
        "recently played",
        "what have i been",
        "my listening",
        "my history",
        "i've been listening",
        "last week",
        "my taste",
        "my playlists",
        "what did i listen",
        "my spotify",
    ],
    "explore_my_taste": [
        "my top",
        "top tracks",
        "top artists",
        "what do i like",
        "what kind of music",
        "my music profile",
        "what genres",
        "music taste",
        "my vibe",
    ],
    "discover": [
        "discover",
        "surprise me",
        "something new",
        "new music",
        "what should i try",
        "find me something",
        "outside my bubble",
        "underrated",
        "hidden gem",
    ],
    "chit_chat": [
        "hello",
        "hi",
        "hey",
        "thanks",
        "thank you",
        "bye",
        "how are you",
        "what's up",
        "good morning",
        "good night",
    ],
}


def classify_intent(query: str) -> dict[str, Any]:
    """Classify query intent using keyword matching.

    Returns dict with ``intent``, ``confidence``, ``matches``.
    Defaults to ``artist_info`` when no keyword fires.
    """
    query_lower = query.lower()
    scores: dict[str, dict[str, Any]] = {}

    for intent, keywords in INTENT_PATTERNS.items():
        matched = [kw for kw in keywords if kw in query_lower]
        scores[intent] = {"score": len(matched), "matches": matched}

    if not any(s["score"] > 0 for s in scores.values()):
        return {"intent": "artist_info", "confidence": 0.3, "matches": []}

    best = max(scores.keys(), key=lambda k: scores[k]["score"])
    confidence = min(1.0, scores[best]["score"] / 3)
    return {"intent": best, "confidence": confidence, "matches": scores[best]["matches"]}


# =============================================================================
# QUERY EXPANSION (Music Synonyms)
# =============================================================================

MUSIC_SYNONYMS: dict[str, list[str]] = {
    "track": ["song", "tune", "record"],
    "artist": ["musician", "band", "singer", "performer"],
    "similar": ["like", "sounds like", "in the style of", "reminiscent of"],
    "recommend": ["suggest", "find me", "show me"],
}


def expand_query(query: str) -> str:
    """Append up to 2 synonyms per matched term; return expanded query string."""
    query_lower = query.lower()
    added: list[str] = []

    for term, synonyms in MUSIC_SYNONYMS.items():
        if term in query_lower:
            added.extend(synonyms[:2])

    if added:
        return query + " " + " ".join(set(added))
    return query


# =============================================================================
# ENTITY EXTRACTION
# =============================================================================

ENTITY_PATTERNS: dict[str, list[str]] = {
    "mood": [
        "happy",
        "sad",
        "energetic",
        "chill",
        "melancholic",
        "upbeat",
        "dark",
        "romantic",
        "mellow",
        "intense",
        "dreamy",
    ],
    "time_period": [
        "70s",
        "80s",
        "90s",
        "2000s",
        "2010s",
        "recent",
        "classic",
        "vintage",
        "new",
        "modern",
    ],
    "context": [
        "workout",
        "study",
        "party",
        "sleep",
        "focus",
        "driving",
        "dinner",
        "cooking",
        "running",
        "relaxing",
    ],
}


def extract_entities(query: str) -> dict[str, list[str]]:
    """Extract music-domain entity types from query."""
    query_lower = query.lower()
    return {
        etype: [p for p in patterns if p in query_lower]
        for etype, patterns in ENTITY_PATTERNS.items()
        if any(p in query_lower for p in patterns)
    }


# =============================================================================
# QUERY DECOMPOSITION
# =============================================================================


def decompose_query(query: str) -> list[str]:
    """Split complex multi-part queries into sub-queries (max 3)."""
    sub_queries: list[str] = []
    query_lower = query.lower()

    if " and " in query_lower and any(k in query_lower for k in ("who", "what", "recommend")):
        parts = re.split(r"\s+and\s+", query, flags=re.IGNORECASE)
        sub_queries.extend(p.strip() for p in parts if len(p.strip()) > 10)

    if query.count("?") > 1:
        parts = query.split("?")
        sub_queries.extend(p.strip() + "?" for p in parts if len(p.strip()) > 10)

    return sub_queries[:3] if sub_queries else [query]


# =============================================================================
# COMPLEXITY SCORING
# =============================================================================

COMPLEX_TERMS = [
    "compare",
    "difference between",
    "versus",
    "pros and cons",
    "best way to",
    "how does",
    "relationship between",
]


def score_complexity(query: str, entities: dict, sub_queries: list[str]) -> str:
    """Score query complexity → ``'simple'`` | ``'moderate'`` | ``'complex'``."""
    score = 0
    if len(query) > 200:
        score += 2
    elif len(query) > 100:
        score += 1
    if len(sub_queries) > 1:
        score += 2
    if len(entities) > 2:
        score += 1
    if any(term in query.lower() for term in COMPLEX_TERMS):
        score += 2

    if score >= 4:
        return "complex"
    if score >= 2:
        return "moderate"
    return "simple"


# =============================================================================
# RETRIEVAL MODE SELECTION
# =============================================================================

_SNIPPET_INTENTS = {"artist_info", "genre_info"}
_DIRECT_INTENTS = {"chit_chat", "out_of_scope"}


def select_retrieval_mode(intent: str, complexity: str) -> str:
    """Map intent + complexity → retrieval mode.

    Returns:
        ``'snippet'``  — fast DuckDB FTS bypass (simple factual lookups)
        ``'hybrid'``   — vector + term-overlap blend (comparisons, recommendations)
        ``'dense'``    — pure vector search (exploratory / complex)
    """
    if intent in _DIRECT_INTENTS:
        return "dense"  # won't be used (direct path skips retrieval)
    if intent in _SNIPPET_INTENTS and complexity == "simple":
        return "snippet"
    if intent == "recommendation" or complexity == "moderate":
        return "hybrid"
    return "dense"


# =============================================================================
# MAIN QUERY ANALYZER
# =============================================================================


class QueryAnalyzer:
    """Main query analysis component — rule-based, no LLM calls."""

    def __init__(
        self,
        expand_terms: bool = True,
        extract_entities_flag: bool = True,
        decompose: bool = True,
    ) -> None:
        self.expand_terms = expand_terms
        self.extract_entities_flag = extract_entities_flag
        self.decompose = decompose

    def analyze(self, query: str) -> QueryAnalysis:
        """Perform full query analysis and return a QueryAnalysis dataclass."""
        intent_result = classify_intent(query)
        intent = intent_result["intent"]

        expanded_query = expand_query(query) if self.expand_terms else query
        entities = extract_entities(query) if self.extract_entities_flag else {}
        sub_queries = decompose_query(query) if self.decompose else [query]
        complexity = score_complexity(query, entities, sub_queries)
        retrieval_mode = select_retrieval_mode(intent, complexity)

        log.debug(
            "query_analyzer.done",
            intent=intent,
            complexity=complexity,
            retrieval_mode=retrieval_mode,
            n_sub_queries=len(sub_queries),
        )
        return QueryAnalysis(
            original_query=query,
            intent=intent,
            complexity=complexity,
            expanded_query=expanded_query,
            entities=entities,
            sub_queries=sub_queries,
            retrieval_mode=retrieval_mode,
            confidence=intent_result["confidence"],
        )
