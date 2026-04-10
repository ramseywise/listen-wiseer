from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from .retrieval import GradedChunk, Intent, QueryPlan, RankedChunk, RetrievalResult


class RAGState(TypedDict, total=False):
    """LangGraph state for the music RAG pipeline.

    ``total=False`` makes all keys optional so partial updates work cleanly.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    query: str
    standalone_query: str
    intent: Intent
    retrieval_mode: str  # "dense" | "hybrid" | "snippet"
    query_variants: list[str]
    plan: QueryPlan
    retrieved_chunks: list[RetrievalResult]
    graded_chunks: list[GradedChunk]
    reranked_chunks: list[RankedChunk]
    confidence_score: float
    response: str
    citations: list[dict]  # [{url, title}, ...]
    confident: bool
    fallback_requested: bool
    retry_count: int
    trace_id: str


def initial_state(query: str, trace_id: str = "") -> RAGState:
    return RAGState(
        messages=[],
        query=query,
        standalone_query="",
        intent=Intent.ARTIST_INFO,
        retrieval_mode="dense",
        query_variants=[],
        retrieved_chunks=[],
        graded_chunks=[],
        reranked_chunks=[],
        confidence_score=0.0,
        response="",
        citations=[],
        confident=True,
        fallback_requested=False,
        retry_count=0,
        trace_id=trace_id,
    )
