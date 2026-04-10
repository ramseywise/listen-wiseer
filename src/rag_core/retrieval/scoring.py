"""Shared scoring primitives used across retrieval backends."""

from __future__ import annotations

import math


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors. Returns 0.0 for zero-norm inputs."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def term_overlap(query: str, text: str) -> float:
    """BM25-like term overlap: |query_terms ∩ doc_terms| / |query_terms|."""
    q_terms = set(query.lower().split())
    d_terms = set(text.lower().split())
    if not q_terms:
        return 0.0
    return len(q_terms & d_terms) / len(q_terms)
