from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """Shared state flowing through every LangGraph node.

    ``messages`` is the only required field. All other fields are populated by
    upstream nodes (classify_intent, validate_tool_output) and accessed via
    ``state.get("field", default)`` — never direct key access.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    intent: str  # "artist_info", "recommendation", etc.
    intent_confidence: float  # 0.0–1.0 from keyword classifier
    entities: dict  # {"mood": [...], "time_period": [...]}
    query_variants: list[str]  # expanded/decomposed query variants
    tool_validation_retries: int  # 0 initially, max controlled by config
