"""Query understanding layer for pre-retrieval analysis.

Components:
- Intent classification (music domain)
- Query expansion (music synonyms)
- Entity extraction (mood, time period, context)
- Query decomposition (multi-hop)
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
    intent: str  # artist_info, genre_info, recommendation, history, chit_chat
    complexity: str  # simple, moderate, complex
    expanded_query: str
    entities: dict[str, list[str]]  # entity_type -> values
    metadata_filters: dict[str, Any]
    sub_queries: list[str]  # for multi-hop
    confidence: float


# =============================================================================
# INTENT CLASSIFICATION
# =============================================================================

INTENT_PATTERNS: dict[str, dict[str, list[str]]] = {
    "artist_info": {
        "keywords": [
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
    },
    "genre_info": {
        "keywords": [
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
    },
    "recommendation": {
        "keywords": [
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
    },
    "history": {
        "keywords": [
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
    },
    "chit_chat": {
        "keywords": [
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
    },
}


def classify_intent(query: str) -> dict[str, Any]:
    """Classify query intent using keyword matching.

    Args:
        query: User query

    Returns:
        Intent classification with confidence and matched keywords.
    """
    query_lower = query.lower()
    scores: dict[str, dict[str, Any]] = {}

    for intent, patterns in INTENT_PATTERNS.items():
        score = 0
        matches = []

        for keyword in patterns["keywords"]:
            if keyword in query_lower:
                score += 1
                matches.append(keyword)

        scores[intent] = {"score": score, "matches": matches}

    # Default to artist_info if no strong signal
    if not any(s["score"] > 0 for s in scores.values()):
        return {"intent": "artist_info", "confidence": 0.3, "matches": []}

    best_intent = max(scores.keys(), key=lambda k: scores[k]["score"])
    confidence = min(1.0, scores[best_intent]["score"] / 3)

    return {
        "intent": best_intent,
        "confidence": confidence,
        "matches": scores[best_intent]["matches"],
    }


# =============================================================================
# QUERY EXPANSION (Music Synonyms)
# =============================================================================

MUSIC_SYNONYMS: dict[str, list[str]] = {
    "track": ["song", "tune", "record"],
    "artist": ["musician", "band", "singer", "performer"],
    "similar": ["like", "sounds like", "in the style of", "reminiscent of"],
    "recommend": ["suggest", "find me", "show me"],
}


def expand_query(query: str) -> dict[str, Any]:
    """Expand query with music-domain synonyms.

    Args:
        query: Original query

    Returns:
        Expanded query and expansion info.
    """
    query_lower = query.lower()
    expansions_applied = []
    expanded_terms = []

    for term, synonyms in MUSIC_SYNONYMS.items():
        if term in query_lower:
            expansions_applied.append(term)
            expanded_terms.extend(synonyms[:2])  # Add top 2 synonyms

    if expanded_terms:
        expansion_text = " " + " ".join(set(expanded_terms))
        expanded_query = query + expansion_text
    else:
        expanded_query = query

    return {
        "original": query,
        "expanded": expanded_query,
        "terms_expanded": expansions_applied,
        "added_terms": list(set(expanded_terms)),
    }


# =============================================================================
# ENTITY EXTRACTION
# =============================================================================

ENTITY_PATTERNS: dict[str, list[str]] = {
    "mood": [
        "happy", "sad", "energetic", "chill", "melancholic", "upbeat",
        "dark", "romantic", "mellow", "intense", "dreamy",
    ],
    "time_period": [
        "70s", "80s", "90s", "2000s", "2010s", "recent",
        "classic", "vintage", "new", "modern",
    ],
    "context": [
        "workout", "study", "party", "sleep", "focus", "driving",
        "dinner", "cooking", "running", "relaxing",
    ],
}


def extract_entities(query: str) -> dict[str, list[str]]:
    """Extract music-domain entities for metadata filtering.

    Args:
        query: User query

    Returns:
        Dictionary of entity_type -> extracted values.
    """
    query_lower = query.lower()
    entities: dict[str, list[str]] = {}

    for entity_type, patterns in ENTITY_PATTERNS.items():
        matched = [p for p in patterns if p in query_lower]
        if matched:
            entities[entity_type] = matched

    return entities


# =============================================================================
# METADATA FILTER GENERATION
# =============================================================================


def generate_metadata_filters(
    intent: str,
    entities: dict[str, list[str]],
    query: str,
) -> dict[str, Any]:
    """Generate metadata filters for retrieval.

    Args:
        intent: Classified intent
        entities: Extracted entities
        query: Original query

    Returns:
        Metadata filters for retriever.
    """
    filters: dict[str, Any] = {}

    if intent == "artist_info":
        filters["source_types"] = ["wikipedia", "biography"]
    elif intent == "genre_info":
        filters["source_types"] = ["wikipedia", "genre_guide"]
    elif intent == "recommendation":
        filters["source_types"] = ["corpus", "playlist"]

    if "mood" in entities:
        filters["mood"] = entities["mood"]
    if "time_period" in entities:
        filters["time_period"] = entities["time_period"]

    return filters


# =============================================================================
# QUERY DECOMPOSITION (Multi-hop)
# =============================================================================


def decompose_query(query: str) -> list[str]:
    """Decompose complex query into sub-queries.

    Args:
        query: Complex user query

    Returns:
        List of sub-queries for multi-hop retrieval.
    """
    sub_queries: list[str] = []
    query_lower = query.lower()

    # Split on "and" with question-like patterns
    if " and " in query_lower and any(
        k in query_lower for k in ("who", "what", "recommend")
    ):
        parts = re.split(r"\s+and\s+", query, flags=re.IGNORECASE)
        if len(parts) > 1:
            sub_queries.extend([p.strip() for p in parts if len(p.strip()) > 10])

    # Multiple question marks
    if query.count("?") > 1:
        parts = query.split("?")
        sub_queries.extend([p.strip() + "?" for p in parts if len(p.strip()) > 10])

    if not sub_queries:
        return [query]

    return sub_queries[:3]  # Max 3 sub-queries


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
    """Score query complexity for routing.

    Args:
        query: User query
        entities: Extracted entities
        sub_queries: Decomposed sub-queries

    Returns:
        Complexity level: simple, moderate, complex.
    """
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
    elif score >= 2:
        return "moderate"
    else:
        return "simple"


# =============================================================================
# MAIN QUERY ANALYZER
# =============================================================================


class QueryAnalyzer:
    """Main query analysis component."""

    def __init__(
        self,
        expand_terms: bool = True,
        extract_entities_flag: bool = True,
        decompose: bool = True,
    ):
        """Initialize query analyzer.

        Args:
            expand_terms: Whether to expand domain terminology
            extract_entities_flag: Whether to extract entities
            decompose: Whether to decompose multi-hop queries
        """
        self.expand_terms = expand_terms
        self.extract_entities_flag = extract_entities_flag
        self.decompose = decompose

    def analyze(self, query: str) -> QueryAnalysis:
        """Perform full query analysis.

        Args:
            query: User query

        Returns:
            Complete query analysis.
        """
        intent_result = classify_intent(query)

        if self.expand_terms:
            expansion = expand_query(query)
            expanded_query = expansion["expanded"]
        else:
            expanded_query = query

        if self.extract_entities_flag:
            entities = extract_entities(query)
        else:
            entities = {}

        metadata_filters = generate_metadata_filters(
            intent_result["intent"], entities, query
        )

        if self.decompose:
            sub_queries = decompose_query(query)
        else:
            sub_queries = [query]

        complexity = score_complexity(query, entities, sub_queries)

        return QueryAnalysis(
            original_query=query,
            intent=intent_result["intent"],
            complexity=complexity,
            expanded_query=expanded_query,
            entities=entities,
            metadata_filters=metadata_filters,
            sub_queries=sub_queries,
            confidence=intent_result["confidence"],
        )
