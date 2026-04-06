from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from .retrieval import GradedChunk, Intent, RetrievalResult


class RAGState(TypedDict):  # TypedDict required by LangGraph StateGraph
    messages: Annotated[list[BaseMessage], add_messages]
    query: str
    standalone_query: str
    intent: Intent
    query_variants: list[str]
    retrieved_chunks: list[RetrievalResult]
    graded_chunks: list[GradedChunk]
    response: str
    trace_id: str
    confident: bool
    retry_count: int  # tracks CRAG retry; max 1


def initial_state(query: str, trace_id: str = "") -> RAGState:
    return RAGState(
        messages=[],
        query=query,
        standalone_query="",
        intent=Intent.ARTIST_INFO,
        query_variants=[],
        retrieved_chunks=[],
        graded_chunks=[],
        response="",
        trace_id=trace_id,
        confident=True,
        retry_count=0,
    )
