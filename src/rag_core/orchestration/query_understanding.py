"""Query understanding layer for pre-retrieval analysis.

Components:
- Intent classification
- Query expansion (domain terminology)
- Entity extraction (metadata filters)
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
    intent: str  # factual, procedural, exploratory, troubleshooting
    complexity: str  # simple, moderate, complex
    expanded_query: str
    entities: dict[str, list[str]]  # entity_type -> values
    metadata_filters: dict[str, Any]
    sub_queries: list[str]  # for multi-hop
    confidence: float


# =============================================================================
# INTENT CLASSIFICATION
# =============================================================================

INTENT_PATTERNS = {
    "factual": {
        "keywords": [
            "hvad er",
            "hvor meget",
            "hvornår",
            "hvor",
            "hvilke",
            "er der",
            "kan jeg",
            "er det muligt",
            "priser",
            "what is",
            "how much",
            "when",
            "which",
        ],
        "indicators": ["?", "kort spørgsmål"],
    },
    "procedural": {
        "keywords": [
            "hvordan kan jeg",
            "hvordan gør jeg",
            "vejledning",
            "trin",
            "opsætte",
            "konfigurere",
            "oprette",
            "tilføje",
            "booke",
            "eksportere",
            "importere",
            "how to",
            "how do i",
            "set up",
            "configure",
        ],
        "indicators": ["trin", "tutorial", "guide"],
    },
    "exploratory": {
        "keywords": [
            "hvorfor",
            "forklare",
            "forskel",
            "sammenligne",
            "betyder",
            "forstår ikke",
            "sammenhæng",
            "hvad bruges",
            "why",
            "explain",
            "difference",
            "compare",
        ],
        "indicators": ["generelt", "overordnet"],
    },
    "troubleshooting": {
        "keywords": [
            "fejl",
            "problem",
            "virker ikke",
            "går ikke",
            "error",
            "bug",
            "fejlbesked",
            "nedbrud",
            "hænger",
            "loader ikke",
            "not working",
            "broken",
            "issue",
        ],
        "indicators": ["hjælp", "akut", "siden"],
    },
}


def classify_intent(query: str) -> dict[str, Any]:
    """Classify query intent.

    Args:
        query: User query

    Returns:
        Intent classification with confidence

    """
    query_lower = query.lower()
    scores = {}

    for intent, patterns in INTENT_PATTERNS.items():
        score = 0
        matches = []

        for keyword in patterns["keywords"]:
            if keyword in query_lower:
                score += 1
                matches.append(keyword)

        for indicator in patterns["indicators"]:
            if indicator in query_lower:
                score += 0.5

        scores[intent] = {"score": score, "matches": matches}

    # Default to factual if no strong signal
    if not any(s["score"] > 0 for s in scores.values()):
        return {"intent": "factual", "confidence": 0.3, "matches": []}

    best_intent = max(scores.keys(), key=lambda k: scores[k]["score"])
    confidence = min(1.0, scores[best_intent]["score"] / 3)

    return {
        "intent": best_intent,
        "confidence": confidence,
        "matches": scores[best_intent]["matches"],
    }


# =============================================================================
# QUERY EXPANSION (Domain Terminology)
# =============================================================================

# Danish SaaS/help-desk terminology expansion
TERM_EXPANSIONS = {
    # Billing / subscription
    "faktura": ["invoice", "regning", "betalingsdokument"],
    "abonnement": ["subscription", "plan", "licens"],
    "betaling": ["payment", "fakturering", "opkrævning"],
    "refusion": ["refund", "tilbagebetaling", "kreditnota"],
    # Account / access
    "adgangskode": ["password", "kodeord", "login"],
    "bruger": ["user", "konto", "account", "profil"],
    "tilladelser": ["permissions", "adgang", "roller", "rights"],
    "sso": ["single sign-on", "saml", "oauth"],
    # Integrations
    "integration": ["connector", "api", "webhook", "sync"],
    "api": ["rest api", "integration", "endpoint", "nøgle"],
    "eksport": ["export", "download", "udtræk", "data"],
    "import": ["import", "upload", "indlæsning"],
    # Support concepts
    "fejl": ["error", "problem", "issue", "bug"],
    "rapport": ["report", "rapportering", "analyse"],
    "notifikation": ["notification", "besked", "alert", "e-mail"],
}


def expand_query(query: str) -> dict[str, Any]:
    """Expand query with domain-specific terminology.

    Args:
        query: Original query

    Returns:
        Expanded query and expansion info

    """
    query_lower = query.lower()
    expansions_applied = []
    expanded_terms = []

    for term, expansions in TERM_EXPANSIONS.items():
        if term in query_lower:
            expansions_applied.append(term)
            expanded_terms.extend(expansions[:2])  # Add top 2 expansions

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


def extract_entities(query: str) -> dict[str, list[str]]:
    """Extract entities for metadata filtering.

    Args:
        query: User query

    Returns:
        Dictionary of entity_type -> extracted values

    """
    entities: dict[str, list[str]] = {
        "ticket_ids": [],
        "invoice_numbers": [],
        "dates": [],
        "amounts": [],
        "emails": [],
    }

    # Ticket / case IDs
    ticket_ids = re.findall(r"\b(?:sag|ticket|#)\s*(\d{4,8})\b", query, re.IGNORECASE)
    entities["ticket_ids"].extend(ticket_ids)

    # Invoice numbers
    invoice_nums = re.findall(r"\b(?:faktura|inv|INV)[-\s]?(\d{4,10})\b", query, re.IGNORECASE)
    entities["invoice_numbers"].extend(invoice_nums)

    # Dates (DD.MM.YYYY or DD/MM/YYYY)
    dates = re.findall(r"\b(\d{1,2}[./]\d{1,2}[./]\d{2,4})\b", query)
    entities["dates"].extend(dates)

    # Amounts (DKK, kr, EUR)
    amounts = re.findall(r"(\d+(?:[.,]\d{2})?)\s*(?:kr|DKK|EUR|€)", query)
    entities["amounts"].extend(amounts)

    # Email addresses
    emails = re.findall(r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b", query, re.IGNORECASE)
    entities["emails"].extend(emails)

    # Clean up empty lists
    return {k: v for k, v in entities.items() if v}


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
        Metadata filters for retriever

    """
    filters: dict[str, Any] = {}

    if intent == "procedural":
        filters["source_types"] = ["help_center", "tutorial", "guide"]
    elif intent == "troubleshooting":
        filters["source_types"] = ["help_center", "faq", "troubleshooting"]
    elif intent == "factual":
        filters["source_types"] = ["faq", "help_center"]

    return filters


# =============================================================================
# QUERY DECOMPOSITION (Multi-hop)
# =============================================================================


def decompose_query(query: str) -> list[str]:
    """Decompose complex query into sub-queries.

    Args:
        query: Complex user query

    Returns:
        List of sub-queries for multi-hop retrieval

    """
    sub_queries = []
    query_lower = query.lower()

    # Split on "og" (Danish "and") with question-like patterns
    if " og " in query_lower and ("hvordan" in query_lower or "hvad" in query_lower):
        parts = re.split(r"\s+og\s+", query, flags=re.IGNORECASE)
        if len(parts) > 1:
            sub_queries.extend([p.strip() for p in parts if len(p.strip()) > 20])

    # Multiple question marks
    if query.count("?") > 1:
        parts = query.split("?")
        sub_queries.extend([p.strip() + "?" for p in parts if len(p.strip()) > 15])

    if not sub_queries:
        return [query]

    return sub_queries[:3]  # Max 3 sub-queries


# =============================================================================
# COMPLEXITY SCORING
# =============================================================================


def score_complexity(query: str, entities: dict, sub_queries: list[str]) -> str:
    """Score query complexity for routing.

    Args:
        query: User query
        entities: Extracted entities
        sub_queries: Decomposed sub-queries

    Returns:
        Complexity level: simple, moderate, complex

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

    complex_terms = [
        "sammenhæng",
        "forskel",
        "sammenligne",
        "hvornår skal",
        "bedste måde",
    ]
    if any(term in query.lower() for term in complex_terms):
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
        extract_entities: bool = True,
        decompose: bool = True,
    ):
        """Initialize query analyzer.

        Args:
            expand_terms: Whether to expand domain terminology
            extract_entities: Whether to extract entities
            decompose: Whether to decompose multi-hop queries

        """
        self.expand_terms = expand_terms
        self.extract_entities_flag = extract_entities
        self.decompose = decompose

    def analyze(self, query: str) -> QueryAnalysis:
        """Perform full query analysis.

        Args:
            query: User query

        Returns:
            Complete query analysis

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

        metadata_filters = generate_metadata_filters(intent_result["intent"], entities, query)

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
