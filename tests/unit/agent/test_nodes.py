"""Unit tests for agent node functions.

trim_history is tested by importing it directly from langchain_core + settings,
avoiding the agent.tools import chain that requires DuckDB.

Memory-related node tests (episodic formatting, memory stats) use replicated
logic to avoid importing agent.nodes directly (DuckDB dep).
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, HumanMessage, trim_messages
from langgraph.store.memory import InMemoryStore

from utils.config import settings


def _run(coro):
    """Helper to run async in sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


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


# ---------------------------------------------------------------------------
# Episodic formatting (replicated from nodes.py to avoid DuckDB import)
# ---------------------------------------------------------------------------

_EPISODIC_RECALL_LIMIT = 2


def _format_episodic_examples(items: list) -> str:
    """Replicate nodes._format_episodic_examples."""
    if not items:
        return ""
    lines = ["<past_sessions>"]
    for item in items:
        val = item.value
        lines.append(f"User request: {val.get('request', '?')}")
        lines.append(f"Tracks returned: {val.get('tracks', '?')}")
        lines.append("---")
    lines.append("</past_sessions>")
    return "\n".join(lines)


def test_episodic_format_empty() -> None:
    """No items produces empty string."""
    assert _format_episodic_examples([]) == ""


def test_episodic_format_with_items() -> None:
    """Items produce a structured XML-like block."""
    store = InMemoryStore()
    _run(store.aput(("ns",), "k1", {"request": "zouk recs", "tracks": "1. ZoukA 2. ZoukB"}))
    items = _run(store.asearch(("ns",), limit=5))

    result = _format_episodic_examples(items)
    assert "<past_sessions>" in result
    assert "zouk recs" in result
    assert "ZoukA" in result


# ---------------------------------------------------------------------------
# Memory stats (replicated from nodes.py to avoid DuckDB import)
# ---------------------------------------------------------------------------


async def _build_memory_stats(store: InMemoryStore, user_id: str) -> str:
    """Replicate nodes._build_memory_stats."""
    session_items = await store.asearch(("enoa", user_id, "sessions"), limit=100)
    taste_items = await store.asearch(("enoa", user_id, "taste"), limit=100)
    has_strategy = await store.aget(("enoa", user_id, "strategy"), "system_instructions")

    session_count = len(session_items)
    taste_count = len(taste_items)
    strategy_status = "active" if has_strategy else "default"

    if session_count == 0 and taste_count == 0 and not has_strategy:
        return ""

    return (
        "<memory_stats>\n"
        f"Past sessions on record: {session_count}\n"
        f"Taste facts stored: {taste_count}\n"
        f"Strategy profile: {strategy_status}\n"
        "</memory_stats>"
    )


def test_memory_stats_empty_store() -> None:
    """Empty store produces empty stats string."""
    store = InMemoryStore()
    result = _run(_build_memory_stats(store, "user1"))
    assert result == ""


def test_memory_stats_with_sessions() -> None:
    """Populated store produces stats block with counts."""
    store = InMemoryStore()
    _run(store.aput(("enoa", "user1", "sessions"), "s1", {"request": "zouk", "tracks": "t1"}))
    _run(store.aput(("enoa", "user1", "sessions"), "s2", {"request": "bossa", "tracks": "t2"}))
    _run(store.aput(("enoa", "user1", "taste"), "t1", {"fact": "loves zouk"}))

    result = _run(_build_memory_stats(store, "user1"))
    assert "<memory_stats>" in result
    assert "Past sessions on record: 2" in result
    assert "Taste facts stored: 1" in result
    assert "Strategy profile: default" in result


def test_memory_stats_with_strategy() -> None:
    """Active strategy shows 'active' status."""
    store = InMemoryStore()
    _run(
        store.aput(
            ("enoa", "user1", "strategy"),
            "system_instructions",
            {"instructions": "be concise"},
        )
    )

    result = _run(_build_memory_stats(store, "user1"))
    assert "Strategy profile: active" in result
