"""Unit tests for agent node functions.

trim_history is tested by importing it directly from langchain_core + settings,
avoiding the agent.tools import chain that requires DuckDB.

Memory-related tests import the real agent.memory_helpers functions directly —
that module has no DuckDB dependency, unlike agent.graph_nodes.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, trim_messages
from langgraph.store.memory import InMemoryStore

from agent.memory_helpers import build_memory_stats, format_episodic_examples
from utils.config import settings


def _trim_history_impl(state: dict) -> dict:
    """Replicate trim_history logic without importing agent.graph_nodes (avoids DuckDB)."""
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


# ---------------------------------------------------------------------------
# Episodic formatting
# ---------------------------------------------------------------------------


def test_episodic_format_empty() -> None:
    """No items produces empty string."""
    assert format_episodic_examples([]) == ""


async def test_episodic_format_with_items() -> None:
    """Items produce a structured XML-like block."""
    store = InMemoryStore()
    await store.aput(("ns",), "k1", {"request": "zouk recs", "tracks": "1. ZoukA 2. ZoukB"})
    items = await store.asearch(("ns",), limit=5)

    result = format_episodic_examples(items)
    assert "<past_sessions>" in result
    assert "zouk recs" in result
    assert "ZoukA" in result


# ---------------------------------------------------------------------------
# Memory stats
# ---------------------------------------------------------------------------


async def test_memory_stats_empty_store() -> None:
    """Empty store produces empty stats string."""
    store = InMemoryStore()
    result = await build_memory_stats(store, "user1")
    assert result == ""


async def test_memory_stats_with_sessions() -> None:
    """Populated store produces stats block with counts."""
    store = InMemoryStore()
    await store.aput(("enoa", "user1", "sessions"), "s1", {"request": "zouk", "tracks": "t1"})
    await store.aput(("enoa", "user1", "sessions"), "s2", {"request": "bossa", "tracks": "t2"})
    await store.aput(("enoa", "user1", "taste"), "t1", {"fact": "loves zouk"})

    result = await build_memory_stats(store, "user1")
    assert "<memory_stats>" in result
    assert "Past sessions on record: 2" in result
    assert "Taste facts stored: 1" in result
    assert "Strategy profile: default" in result


async def test_memory_stats_with_strategy() -> None:
    """Active strategy shows 'active' status."""
    store = InMemoryStore()
    await store.aput(
        ("enoa", "user1", "strategy"),
        "system_instructions",
        {"instructions": "be concise"},
    )

    result = await build_memory_stats(store, "user1")
    assert "Strategy profile: active" in result
