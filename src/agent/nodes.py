"""LangGraph node functions for the listen-wiseer ReAct agent."""

from __future__ import annotations

import uuid
from typing import Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, trim_messages
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agent.memory_store import get_procedural_prompt
from agent.state import AgentState
from agent.tools import ALL_TOOLS
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# LLM — shared across nodes, instantiated once at module load
# ---------------------------------------------------------------------------

_llm = ChatAnthropic(
    model=settings.anthropic_model,
    api_key=settings.anthropic_api_key,
)
_llm_with_tools = _llm.bind_tools(ALL_TOOLS)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are listen-wiseer, a personal music assistant.

You help users explore their Spotify listening history, discover new music
through content-based recommendations, and learn about artists.

## Tool usage

- **recommend_similar_tracks** — "find tracks like X" (needs a Spotify track ID)
- **recommend_for_artist** — "recommend tracks by/like artist X" (needs a Spotify artist ID)
- **recommend_by_genre** — genre-based requests, e.g. "zouk", "bossa nova", "house" (pass the genre name)
- **recommend_for_playlist** — playlist-based recommendations (needs a Spotify playlist ID)
- **get_recently_played** — see what the user has been listening to
- **search_tracks** — find a specific track or artist on Spotify (returns track IDs you can feed into other tools)
- **manage_taste_memory** — store a fact about the user's musical taste for future sessions
- **search_taste_memory** — recall stored facts about the user's taste preferences

If the user gives you an artist/track *name* instead of a Spotify ID, use
**search_tracks** first to resolve the ID, then call the appropriate recommend tool.

## Memory

You have access to memory tools that persist across sessions:
- Use **manage_taste_memory** to record important user preferences (e.g. "prefers zouk over kizomba", "dislikes electronic BPM > 140").
- Use **search_taste_memory** when a user asks something that their past preferences might inform.
- Past recommendation sessions are automatically recalled as examples when relevant.

## Response style

- Present recommendations as a numbered list with brief notes
- Be concise — 3-5 sentences unless the user asks for detail
- If a tool returns no results, explain why and suggest alternatives
"""

# Maximum number of past sessions to inject as few-shot examples
_EPISODIC_RECALL_LIMIT = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_user_id(config: RunnableConfig) -> str:
    """Extract langgraph_user_id from config, defaulting to 'default'."""
    return config.get("configurable", {}).get("langgraph_user_id", "default")


def _format_episodic_examples(items: list) -> str:
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


async def _recall_episodic(
    store: BaseStore,
    user_id: str,
    query: str,
) -> str:
    """Search episodic memory for similar past sessions."""
    items = await store.asearch(
        ("enoa", user_id, "sessions"),
        query=query,
        limit=_EPISODIC_RECALL_LIMIT,
    )
    return _format_episodic_examples(items)


async def _store_episodic(
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


def _extract_recommendation_summary(messages: list) -> str | None:
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


def _find_user_request(messages: list) -> str | None:
    """Find the first human message in the conversation."""
    for msg in messages:
        if isinstance(msg, HumanMessage):
            return msg.content
    return None


async def _build_memory_stats(store: BaseStore, user_id: str) -> str:
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


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def trim_history(state: AgentState) -> AgentState:
    """Trim conversation history to stay within context limits.

    Uses message count (not token count) for simplicity. Keeps the most recent
    messages and preserves the system message if present.
    """
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
    log.info(
        "agent.trim_history",
        original_count=len(messages),
        trimmed_count=len(trimmed),
    )
    return {"messages": trimmed}


async def agent_node(
    state: AgentState,
    config: RunnableConfig,
    *,
    store: Optional[BaseStore] = None,
) -> AgentState:
    """Core agent node — call the LLM with tools bound.

    When a store is available:
    - Searches episodic memory for similar past sessions (few-shot examples).
    - After a recommendation, stores the session for future recall.
    """
    user_id = _extract_user_id(config)
    prompt_parts = [SYSTEM_PROMPT]

    # --- Procedural memory (per-user strategy) ---
    if store is not None:
        procedural = await get_procedural_prompt(user_id, store)
        if procedural:
            prompt_parts.append(f"<user_strategy>\n{procedural}\n</user_strategy>")

    # --- Episodic recall ---
    if store is not None:
        user_request = _find_user_request(state["messages"])
        if user_request:
            episodic_block = await _recall_episodic(store, user_id, user_request)
            if episodic_block:
                prompt_parts.append(episodic_block)

    # --- Memory statistics ---
    if store is not None:
        stats = await _build_memory_stats(store, user_id)
        if stats:
            prompt_parts.append(stats)

    messages = [SystemMessage(content="\n\n".join(prompt_parts))] + state["messages"]
    response = await _llm_with_tools.ainvoke(messages)

    # --- Episodic store (after successful recommendation) ---
    if store is not None and not getattr(response, "tool_calls", None):
        user_request = _find_user_request(state["messages"])
        summary = _extract_recommendation_summary(state["messages"] + [response])
        if user_request and summary:
            await _store_episodic(store, user_id, user_request, summary)

    return {"messages": [response]}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_after_agent(state: AgentState) -> str:
    """Route after the agent node: tools if tool_calls present, else END."""
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "call_tools"
    return "__end__"
