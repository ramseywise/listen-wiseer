from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Shared state flowing through every LangGraph node.

    Messages-only for Phase 3c. Additional fields (context_docs, etc.)
    will be added in Phase 4 when RAG needs them.
    """

    messages: Annotated[list[BaseMessage], add_messages]
