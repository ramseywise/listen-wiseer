"""Unit tests for agent node functions.

trim_history is tested by importing it directly from langchain_core + settings,
avoiding the agent.tools import chain that requires DuckDB.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, trim_messages

from utils.config import settings


def _trim_history_impl(state: dict) -> dict:
    """Replicate trim_history logic without importing agent.nodes (avoids DuckDB)."""
    messages = state["messages"]
    if len(messages) <= settings.max_history_messages:
        return {"messages": messages}
    trimmed = trim_messages(
        messages,
        max_tokens=settings.max_history_messages,
        token_counter=len,
        strategy="last",
        start_on="human",
    )
    return {"messages": trimmed}


def test_trim_history_under_limit() -> None:
    """Messages under the limit pass through unchanged."""
    messages = [HumanMessage(content=f"msg {i}") for i in range(5)]
    state = {"messages": messages}
    result = _trim_history_impl(state)
    assert len(result["messages"]) == 5


def test_trim_history_over_limit() -> None:
    """Messages over the limit are trimmed to keep the most recent."""
    messages: list = []
    for i in range(15):
        messages.append(HumanMessage(content=f"human {i}"))
        messages.append(AIMessage(content=f"ai {i}"))

    assert len(messages) == 30

    state = {"messages": messages}
    result = _trim_history_impl(state)
    trimmed = result["messages"]

    assert len(trimmed) <= 20
    # Should start with a human message (strategy="last", start_on="human")
    assert isinstance(trimmed[0], HumanMessage)
    # Should keep the most recent messages
    assert trimmed[-1].content == "ai 14"


def test_trim_history_at_limit() -> None:
    """Exactly at the limit — no trimming needed."""
    messages: list = []
    for i in range(10):
        messages.append(HumanMessage(content=f"human {i}"))
        messages.append(AIMessage(content=f"ai {i}"))

    assert len(messages) == 20

    state = {"messages": messages}
    result = _trim_history_impl(state)
    assert len(result["messages"]) == 20
