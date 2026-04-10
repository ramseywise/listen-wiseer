from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from .chunks import Chunk


class Intent(StrEnum):
    ARTIST_INFO = "artist_info"  # "who is Aphex Twin?", "tell me about Radiohead"
    GENRE_INFO = "genre_info"  # "what is zouk?", "explain bossa nova"
    RECOMMENDATION = "recommendation"  # "recommend tracks like X", "suggest something"
    HISTORY = "history"  # "what have I been listening to?", "my recent plays"
    CHIT_CHAT = "chit_chat"  # greetings, small talk
    OUT_OF_SCOPE = "out_of_scope"  # unrelated to music


class RetrievalResult(BaseModel):
    chunk: Chunk
    score: float
    source: Literal["vector", "bm25", "hybrid", "snippet"] = "hybrid"


class GradedChunk(BaseModel):
    chunk: Chunk
    score: float
    relevant: bool


class RankedChunk(BaseModel):
    """Output of the reranker — carries a [0,1] relevance score and absolute rank."""

    chunk: Chunk
    relevance_score: float  # sigmoid-normalised cross-encoder logit
    rank: int


class QueryPlan(BaseModel):
    """Structured output of the analyze node."""

    intent: Intent
    routing: str  # "direct" | "retrieve" | "snippet"
    query_variants: list[str] = []
    retrieval_mode: str = "dense"  # "dense" | "hybrid" | "snippet"
    needs_clarification: bool = False
    clarification_question: str | None = None
