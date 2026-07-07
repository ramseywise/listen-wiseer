"""LangGraph node functions for the listen-wiseer ReAct agent."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, trim_messages
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agent.intent import QueryAnalyzer
from agent.memory_helpers import (
    build_memory_stats,
    extract_recommendation_summary,
    find_user_request,
    recall_episodic,
    store_episodic,
)
from agent.memory_store import get_procedural_prompt
from agent.state import AgentState
from agent.tools import ALL_TOOLS
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Query understanding — shared analyzer (no LLM, pure keyword)
# ---------------------------------------------------------------------------

_query_analyzer = QueryAnalyzer()

_INTENT_TOOL_HINTS: dict[str, str] = {
    "artist_info": (
        "Use get_artist_info for metadata, get_artist_context for narrative bio/history, "
        "get_related_artists for similar artists, get_artist_top_tracks for their best songs, "
        "get_artist_albums for discography."
    ),
    "genre_info": (
        "Use get_genre_context for genre-specific queries (origins, history, subgenres). "
        "Fall back to get_artist_context only for artist-style genre questions."
    ),
    "recommendation": "Use recommend_* tools based on the type of recommendation requested.",
    "history": (
        "Use get_recently_played for recent listening. "
        "Use get_top_tracks or get_top_artists for affinity-ranked taste analysis."
    ),
    "explore_my_taste": (
        "Use get_taste_analysis for drift/change questions ('how has my taste changed?'). "
        "Use get_top_artists and get_top_tracks for top-N or genre breakdown queries. "
        "Search taste_memory for stored preferences too."
    ),
    "discover": (
        "Use get_spotify_recommendations seeded from top artists or a track the user mentioned. "
        "Use get_related_artists to surface adjacent artists they may not know."
    ),
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

You help users explore their Spotify listening history, discover new music,
dive deep into artists and genres, and get personalised recommendations.

## Tool usage

### Recommendations (ENOA corpus — personalised to your taste map)
- **recommend_similar_tracks** — "find tracks like X" (needs a Spotify track ID)
- **recommend_for_artist** — "recommend tracks by/like artist X" (needs a Spotify artist ID)
- **recommend_by_genre** — genre-based requests, e.g. "zouk", "bossa nova", "house"
- **recommend_for_playlist** — playlist-based recommendations (needs a Spotify playlist ID)

### Discovery (Spotify-native — good for new/unknown artists)
- **get_spotify_recommendations** — seed-based discovery; use when the artist/track isn't in the local corpus or when the user wants to explore outside their bubble
- **get_related_artists** — "who sounds like X?", "artists similar to X" (needs a Spotify artist ID)

### Taste analysis (user's own listening data)
- **get_taste_analysis** — compare short-term vs long-term top artists to surface drift, new obsessions, and stable staples; use for "how has my taste changed?" queries
- **get_top_tracks** — "my top tracks this month / all time" (time_range: short_term, medium_term, long_term)
- **get_top_artists** — "my top artists", "what genres am I into lately"
- **get_recently_played** — "what have I been listening to recently"
- **get_user_playlists** — list the user's playlists (use to look up a playlist ID)

### Artist deep dives
- **search_tracks** — resolve an artist/track name to a Spotify ID (always do this first)
- **get_artist_info** — genres, popularity, follower count for an artist
- **get_artist_top_tracks** — artist's top 10 tracks (good for seeding recommendations)
- **get_artist_albums** — full discography (albums and singles)
- **get_artist_context** — narrative bio, history, influences, style (Tavily web search)

### Genre deep dives
- **get_genre_context** — genre origins, history, defining characteristics, key artists, subgenres (Tavily web search; prefer over get_artist_context for genre questions)

### Memory & playlist
- **manage_taste_memory** — store a taste preference for future sessions
- **search_taste_memory** — recall stored preferences (always call before making recommendations)
- **create_playlist** — save recommendations as a new Spotify playlist (asks user to confirm)

If the user gives you an artist/track *name* instead of a Spotify ID, use
**search_tracks** first to resolve the ID, then call the appropriate tool.

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_user_id(config: RunnableConfig) -> str:
    """Extract langgraph_user_id from config, defaulting to 'default'."""
    return config.get("configurable", {}).get("langgraph_user_id", "default")


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
    " it ",
    " they ",
    " them ",
    " that ",
    " this ",
    "the artist",
    "the band",
    "the song",
    " their ",
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
        f'- Info about an artist or genre? (e.g. "who is Aphex Twin?")\n'
        f'- Music recommendations? (e.g. "recommend tracks like Boards of Canada")\n'
        f'- Your listening history? (e.g. "what have I been playing?")'
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
        user_request = find_user_request(state["messages"])
        if user_request:
            episodic_block = await recall_episodic(store, user_id, user_request)
            if episodic_block:
                prompt_parts.append(episodic_block)

    # --- Memory statistics ---
    if store is not None:
        stats = await build_memory_stats(store, user_id)
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
        user_request = find_user_request(state["messages"])
        summary = extract_recommendation_summary(state["messages"] + [response])
        if user_request and summary:
            await store_episodic(store, user_id, user_request, summary)

    return {"messages": [response]}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_after_agent(state: AgentState) -> str:
    """Route after the agent node: tools if tool_calls present, else format_response."""
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "call_tools"
    return "format_response"
