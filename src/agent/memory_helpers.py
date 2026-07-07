"""Episodic and procedural memory helpers for the agent node.

Namespaces (see agent/memory_store.py):
    ("enoa", user_id, "sessions")   — episodic: past recommendation sessions
    ("enoa", user_id, "taste")      — semantic: user taste facts
    ("enoa", user_id, "strategy")   — procedural: per-user system prompt tweaks
"""

from __future__ import annotations

import uuid

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.store.base import BaseStore

from utils.logging import get_logger

log = get_logger(__name__)

# Maximum number of past sessions to inject as few-shot examples
EPISODIC_RECALL_LIMIT = 2


def format_episodic_examples(items: list) -> str:
    """Format retrieved episodic memories into a prompt block."""
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


async def recall_episodic(
    store: BaseStore,
    user_id: str,
    query: str,
) -> str:
    """Search episodic memory for similar past sessions."""
    items = await store.asearch(
        ("enoa", user_id, "sessions"),
        query=query,
        limit=EPISODIC_RECALL_LIMIT,
    )
    return format_episodic_examples(items)


async def store_episodic(
    store: BaseStore,
    user_id: str,
    user_request: str,
    track_summary: str,
) -> None:
    """Store a completed recommendation session in episodic memory."""
    await store.aput(
        ("enoa", user_id, "sessions"),
        key=str(uuid.uuid4()),
        value={"request": user_request, "tracks": track_summary},
    )
    log.debug("agent.episodic.stored", user_id=user_id)


def extract_recommendation_summary(messages: list) -> str | None:
    """Extract a brief summary of recommended tracks from the final AI message.

    Returns None if no recommendation was made (e.g. a greeting).
    """
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content
            # Heuristic: recommendations contain numbered lists
            if any(f"{i}." in content for i in range(1, 6)):
                # Take first 500 chars as summary
                return content[:500]
    return None


def find_user_request(messages: list) -> str | None:
    """Find the first human message in the conversation."""
    for msg in messages:
        if isinstance(msg, HumanMessage):
            return msg.content
    return None


async def build_memory_stats(store: BaseStore, user_id: str) -> str:
    """Query store namespace counts and format a memory stats block."""
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
