"""LangGraph node functions for the listen-wiseer ReAct agent."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, trim_messages
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_store
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
from agent.prompts import load_prompt
from agent.state import AgentState
from agent.tools import ALL_TOOLS
from evals.graders.answer_eval import HeuristicChecker
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
# LLM — lazy singleton to avoid module-level instantiation
# ---------------------------------------------------------------------------

_llm_instance: ChatAnthropic | None = None
_llm_with_tools_instance: ChatAnthropic | None = None


def _get_llm() -> ChatAnthropic:
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = ChatAnthropic(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
        )
    return _llm_instance


def _get_llm_with_tools() -> ChatAnthropic:
    global _llm_with_tools_instance
    if _llm_with_tools_instance is None:
        _llm_with_tools_instance = _get_llm().bind_tools(ALL_TOOLS)
    return _llm_with_tools_instance


# ---------------------------------------------------------------------------
# System prompt — loaded from src/agent/prompts/system.md
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = load_prompt("system")


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
        token_counter=lambda _: 1,
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

    Reuses the shared LLM singleton (Haiku) — no separate instance needed.
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
        for m in messages[-5:]
    )
    prompt = (
        "Rewrite the following question as a standalone question that doesn't "
        "require the conversation history to understand. Only output the "
        "rewritten question, nothing else.\n\n"
        f"History:\n{history}\n\n"
        f"Question: {query}\n\n"
        "Standalone question:"
    )
    response = await _get_llm().ainvoke(
        [HumanMessage(content=prompt)],
        config={"timeout": settings.agent_timeout_seconds},
    )
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

    # `from __future__ import annotations` stringifies the ``store`` parameter's
    # type hint, so LangGraph no longer auto-injects the compiled store into it
    # (regressed in langgraph 1.3+). Resolve it from the runtime instead.
    if store is None:
        try:
            store = get_store()
        except RuntimeError:
            store = None

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
    response = await _get_llm_with_tools().ainvoke(
        messages,
        config={"timeout": settings.agent_timeout_seconds},
    )

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
    if not state["messages"]:
        return "format_response"
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "call_tools"
    return "format_response"


# ---------------------------------------------------------------------------
# Verification loop — maker/checker
# ---------------------------------------------------------------------------

_heuristic_checker = HeuristicChecker()


async def verify_answer(state: AgentState) -> dict:
    """Checker node — validates the formatted answer with heuristic grading.

    Sits after ``format_response``. If the answer fails the quality threshold
    and the retry cap has not been reached, injects the checker critique back
    into the message list so the agent can revise.

    State written:
    - ``verification_retries``: incremented on failure
    - ``checker_critique``: critique text (empty on pass)
    - ``messages``: critique injected as HumanMessage on failure
    """
    agent_response = state.get("agent_response", {})
    answer = agent_response.get("message", "")
    retries = state.get("verification_retries", 0)
    max_retries = settings.max_verification_retries

    # Collect tool outputs from the current turn (stop at last HumanMessage)
    messages = state.get("messages", [])
    tool_outputs: list[str] = []
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            break
        if hasattr(msg, "type") and msg.type == "tool":
            tool_outputs.append(str(msg.content))

    # Extract the original user question
    question = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            question = str(msg.content)
            break

    result = _heuristic_checker.check(
        query_id=f"verify-{retries}",
        question=question,
        answer=answer,
        tool_outputs=tool_outputs,
    )

    log.info(
        "agent.verify_answer",
        score=result.score,
        is_correct=result.is_correct,
        reasoning=result.reasoning,
        retries=retries,
        max_retries=max_retries,
    )

    if result.is_correct or result.score >= settings.verification_score_threshold:
        return {"verification_retries": retries, "checker_critique": ""}

    if retries >= max_retries:
        log.warning(
            "agent.verify_answer.cap_reached",
            retries=retries,
            score=result.score,
            reasoning=result.reasoning,
        )
        return {"verification_retries": retries, "checker_critique": result.reasoning}

    critique = (
        f"[Checker] Your answer did not meet quality standards "
        f"(score {result.score:.2f}, threshold {settings.verification_score_threshold}). "
        f"Reason: {result.reasoning}. "
        f"Please revise your answer to better address the query."
    )
    log.info("agent.verify_answer.retry", retry=retries + 1, critique=critique)
    return {
        "messages": [HumanMessage(content=critique)],
        "verification_retries": retries + 1,
        "checker_critique": result.reasoning,
    }


def route_after_verify(state: AgentState) -> str:
    """Route after verify_answer: retry agent if critique present, else END."""
    retries = state.get("verification_retries", 0)
    critique = state.get("checker_critique", "")
    max_retries = settings.max_verification_retries

    # If a critique was injected and we haven't exhausted retries, loop back
    if critique and retries <= max_retries:
        last_messages = state.get("messages", [])
        if last_messages and isinstance(last_messages[-1], HumanMessage):
            return "agent"
    return "END"
