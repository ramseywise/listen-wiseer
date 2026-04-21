"""LangGraph node functions for the listen-wiseer ReAct agent."""

from __future__ import annotations

import re
import uuid

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, trim_messages
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agent.memory_store import get_procedural_prompt
from agent.state import AgentState
from agent.tools import ALL_TOOLS
from rag_core.orchestration.query_understanding import QueryAnalyzer
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Query understanding — shared analyzer (no LLM, pure keyword)
# ---------------------------------------------------------------------------

_query_analyzer = QueryAnalyzer()

_INTENT_TOOL_HINTS: dict[str, str] = {
    "artist_info": "Use get_artist_context to answer questions about this artist.",
    "genre_info": "Use get_artist_context with the genre name to get genre info.",
    "recommendation": "Use recommend_* tools based on the type of recommendation requested.",
    "history": "Use get_recently_played to fetch the user's listening history.",
    "chit_chat": "Respond directly without using tools.",
}

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
- **get_related_artists** — "who sounds like X?", "artists similar to X" (needs a Spotify artist ID)
- **get_artist_context** — "who is X?", "tell me about X", artist trivia, history, influences, genre info
- **create_playlist** — save recommendations as a new Spotify playlist (asks user to confirm before writing)
- **manage_taste_memory** — store a fact about the user's musical taste for future sessions
- **search_taste_memory** — recall stored facts about the user's taste preferences

If the user gives you an artist/track *name* instead of a Spotify ID, use
**search_tracks** first to resolve the ID, then call the appropriate recommend tool.

## Memory

You have access to memory tools that persist across sessions:
- **Always** call **search_taste_memory** before making any recommendation — it returns stored preferences (genres, moods, dislikes) that should shape your picks.
- Use **manage_taste_memory** to record important user preferences whenever the user expresses a strong like, dislike, or preference (e.g. "prefers zouk over kizomba", "dislikes electronic BPM > 140").
- Past recommendation sessions are automatically recalled as examples when relevant.

## Chit-chat

If the user's message is conversational (greetings, follow-ups, thanks, yes/no confirmations), respond directly without calling any tools. Do not force a tool call for small talk.

## Response style

- Present recommendations as a numbered list with brief notes (why this track fits)
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


async def classify_intent_node(state: AgentState) -> dict:
    """Classify query intent and extract entities. No LLM call — pure keyword."""
    messages = state.get("messages", [])
    query = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            query = str(msg.content)
            break

    analysis = _query_analyzer.analyze(query)
    log.info(
        "agent.classify_intent",
        intent=analysis.intent,
        confidence=analysis.confidence,
        entities=analysis.entities,
        complexity=analysis.complexity,
    )
    return {
        "intent": analysis.intent,
        "intent_confidence": analysis.confidence,
        "entities": analysis.entities,
        "query_variants": analysis.sub_queries[:3],
    }


# ---------------------------------------------------------------------------
# Query rewriting — coreference resolution for multi-turn
# ---------------------------------------------------------------------------

_COREFERENCE_SIGNALS = [
    " it ", " they ", " them ", " that ", " this ",
    "the artist", "the band", "the song", " their ",
]


async def rewrite_query(state: AgentState) -> dict:
    """Rewrite query as standalone if multi-turn with coreference signals.

    Reuses the module-level ``_llm`` (Haiku) — no separate instance needed.
    Single-turn or no-pronoun queries pass through unchanged.
    """
    messages = state.get("messages", [])
    if len(messages) <= 1:
        return {}  # single turn — no rewrite

    query = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            query = str(msg.content)
            break

    padded = f" {query.lower()} "
    if not any(signal in padded for signal in _COREFERENCE_SIGNALS):
        return {}  # no coreference — skip

    history = "\n".join(
        f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}"
        for m in messages[-5:-1]
    )
    prompt = (
        "Rewrite the following question as a standalone question that doesn't "
        "require the conversation history to understand. Only output the "
        "rewritten question, nothing else.\n\n"
        f"History:\n{history}\n\n"
        f"Question: {query}\n\n"
        "Standalone question:"
    )
    response = await _llm.ainvoke([HumanMessage(content=prompt)])
    rewritten = str(response.content).strip()
    log.info("agent.rewrite_query", original=query, rewritten=rewritten)

    new_messages = list(messages[:-1]) + [HumanMessage(content=rewritten)]
    return {"messages": new_messages}


def route_after_classify(state: AgentState) -> str:
    """Route based on intent confidence: low -> clarify, high -> proceed."""
    confidence = state.get("intent_confidence", 0.0)
    intent = state.get("intent", "")

    # Chit-chat always proceeds (no clarification needed)
    if intent == "chit_chat":
        return "rewrite_query"

    if confidence < settings.intent_confidence_threshold:
        return "clarify_or_proceed"
    return "rewrite_query"


async def clarify_or_proceed(state: AgentState) -> dict:
    """Inject a clarification request when intent confidence is low.

    Returns an AIMessage asking the user to be more specific. The graph
    routes to __end__ after this node — the user's next message re-enters
    the graph with more context.
    """
    intent = state.get("intent", "unknown")
    entities = state.get("entities", {})
    query = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            query = str(msg.content)
            break

    # Build contextual clarification
    if entities:
        entity_hint = f" I can see you're interested in: {entities}."
    else:
        entity_hint = ""

    clarification = (
        f"I want to make sure I help you with the right thing.{entity_hint} "
        f"Could you clarify what you're looking for? For example:\n"
        f"- Info about an artist or genre? (e.g. \"who is Aphex Twin?\")\n"
        f"- Music recommendations? (e.g. \"recommend tracks like Boards of Canada\")\n"
        f"- Your listening history? (e.g. \"what have I been playing?\")"
    )
    log.info(
        "agent.clarify",
        intent=intent,
        confidence=state.get("intent_confidence", 0.0),
        query=query,
    )
    return {"messages": [AIMessage(content=clarification)]}


async def agent_node(
    state: AgentState,
    config: RunnableConfig,
    *,
    store: BaseStore | None = None,
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

    # --- Intent hint (from classify_intent_node) ---
    intent = state.get("intent", "")
    entities = state.get("entities", {})
    intent_hint = _INTENT_TOOL_HINTS.get(intent, "")
    if intent_hint:
        intent_block = f"<query_classification>\nIntent: {intent}\n{intent_hint}"
        if entities:
            intent_block += f"\nExtracted entities: {entities}"
        intent_block += "\n</query_classification>"
        prompt_parts.append(intent_block)

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
# Post-tool output validation
# ---------------------------------------------------------------------------

_TOOL_INTENT_MAP: dict[str, set[str]] = {
    "artist_info": {"get_artist_context"},
    "genre_info": {"get_artist_context", "recommend_by_genre"},
    "recommendation": {
        "recommend_similar_tracks",
        "recommend_for_artist",
        "recommend_by_genre",
        "recommend_for_playlist",
        "get_related_artists",
        "search_tracks",
    },
    "history": {"get_recently_played"},
}

_ERROR_SIGNALS = [
    "failed to fetch",
    "not found",
    "not available",
    "engine not available",
    "no results",
    "no recently played",
    "no tracks found",
]


async def validate_tool_output(state: AgentState) -> dict:
    """Validate tool output against query intent. No LLM call.

    Checks:
    1. Tool returned non-empty, non-error content
    2. Tool aligns with classified intent
    3. Extracted entities appear in output (soft check — log only)

    On failure: injects corrective hint, increments retry counter.
    On success or retry exhausted: passes through.
    """
    messages = state.get("messages", [])
    intent = state.get("intent", "")
    entities = state.get("entities", {})
    retries = state.get("tool_validation_retries", 0)
    max_retries = settings.max_tool_validation_retries

    # Find the most recent ToolMessage(s)
    tool_messages = []
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "tool":
            tool_messages.append(msg)
        elif tool_messages:
            break  # stop at first non-tool message after collecting tools

    if not tool_messages:
        return {}  # no tool output to validate

    issues: list[str] = []

    # Check 1: Empty or error output
    for tool_msg in tool_messages:
        content = str(tool_msg.content).lower()
        if not content.strip():
            issues.append("Tool returned empty output.")
        elif any(signal in content for signal in _ERROR_SIGNALS):
            issues.append(f"Tool may have failed: {str(tool_msg.content)[:100]}")

    # Check 2: Intent-tool alignment
    expected_tools = _TOOL_INTENT_MAP.get(intent, set())
    if expected_tools:
        used_tools = {
            tool_msg.name
            for tool_msg in tool_messages
            if hasattr(tool_msg, "name")
        }
        if used_tools and not used_tools & expected_tools:
            issues.append(
                f"Intent was '{intent}' but tools used were {used_tools}. "
                f"Expected one of: {expected_tools}."
            )

    # Check 3: Entity coverage (soft — only log, don't fail)
    if entities and not issues:
        all_output = " ".join(str(tool_msg.content).lower() for tool_msg in tool_messages)
        missing_entities = []
        for entity_type, values in entities.items():
            for val in values:
                if val.lower() not in all_output:
                    missing_entities.append(f"{entity_type}:{val}")
        if missing_entities:
            log.debug(
                "agent.validate.entity_gap",
                missing=missing_entities,
                intent=intent,
            )

    if not issues or retries >= max_retries:
        if issues:
            log.warning(
                "agent.validate.issues_exhausted",
                issues=issues,
                retries=retries,
            )
        return {}  # pass through

    # Inject corrective hint
    hint = (
        f"[Validation] The previous tool output may not fully address the query. "
        f"Issues: {'; '.join(issues)} "
        f"Consider using a different tool or approach."
    )
    log.info("agent.validate.retry", issues=issues, retry=retries + 1)
    return {
        "messages": [SystemMessage(content=hint)],
        "tool_validation_retries": retries + 1,
    }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_after_agent(state: AgentState) -> str:
    """Route after the agent node: tools if tool_calls present, else format_response."""
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "call_tools"
    return "format_response"


# ---------------------------------------------------------------------------
# Structured response extraction
# ---------------------------------------------------------------------------

_TRACK_LINE_RE = re.compile(
    r"^\d+\.\s+(.+?)(?:\s+\[(?:spotify:track:)?[A-Za-z0-9]+\])?$",
    re.MULTILINE,
)


def format_response(state: AgentState) -> dict:
    """Extract structured data from the final AI message.

    Populates ``agent_response`` with:
    - ``message``: full text of the AI reply
    - ``track_list``: numbered track names parsed from the response (if any)
    """
    messages = state.get("messages", [])
    last = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if not last:
        return {}

    content = str(last.content)
    track_list = [m.group(1).strip() for m in _TRACK_LINE_RE.finditer(content)]

    return {
        "agent_response": {
            "message": content,
            "track_list": track_list[:20],
        }
    }
