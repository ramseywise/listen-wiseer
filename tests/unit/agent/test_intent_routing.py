"""Unit tests for intent routing nodes.

Tests classify_intent_node, route_after_classify, clarify_or_proceed,
and rewrite_query.
Avoids importing agent.graph_nodes directly (DuckDB dep chain) — replicates
node logic inline, matching the pattern in test_nodes.py.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.intent import QueryAnalyzer
from utils.config import settings


def _run(coro):
    """Helper to run async in sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Replicated classify_intent_node (avoids DuckDB import chain)
# ---------------------------------------------------------------------------

_query_analyzer = QueryAnalyzer()

_INTENT_TOOL_HINTS: dict[str, str] = {
    "artist_info": "Use get_artist_context to answer questions about this artist.",
    "genre_info": "Use get_artist_context with the genre name to get genre info.",
    "recommendation": "Use recommend_* tools based on the type of recommendation requested.",
    "history": "Use get_recently_played to fetch the user's listening history.",
    "chit_chat": "Respond directly without using tools.",
}


async def _classify_intent_node(state: dict) -> dict:
    """Replicated from agent.graph_nodes.classify_intent_node."""
    messages = state.get("messages", [])
    query = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            query = str(msg.content)
            break

    analysis = _query_analyzer.analyze(query)
    return {
        "intent": analysis.intent,
        "intent_confidence": analysis.confidence,
        "entities": analysis.entities,
        "query_variants": analysis.sub_queries[:3],
    }


def _route_after_classify(state: dict) -> str:
    """Replicated from agent.graph_nodes.route_after_classify."""
    confidence = state.get("intent_confidence", 0.0)
    intent = state.get("intent", "")

    if intent == "chit_chat":
        return "rewrite_query"

    if confidence < settings.intent_confidence_threshold:
        return "clarify_or_proceed"
    return "rewrite_query"


async def _clarify_or_proceed(state: dict) -> dict:
    """Replicated from agent.graph_nodes.clarify_or_proceed."""
    entities = state.get("entities", {})
    query = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            query = str(msg.content)
            break

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
    return {"messages": [AIMessage(content=clarification)]}


# =============================================================================
# classify_intent_node tests
# =============================================================================


class TestClassifyIntentNode:
    def test_populates_state(self) -> None:
        state = {"messages": [HumanMessage(content="who is Aphex Twin?")]}
        result = _run(_classify_intent_node(state))
        assert "intent" in result
        assert "intent_confidence" in result
        assert "entities" in result
        assert "query_variants" in result

    def test_artist_info(self) -> None:
        state = {"messages": [HumanMessage(content="who is Aphex Twin?")]}
        result = _run(_classify_intent_node(state))
        assert result["intent"] == "artist_info"

    def test_recommendation(self) -> None:
        state = {"messages": [HumanMessage(content="suggest tracks like Radiohead")]}
        result = _run(_classify_intent_node(state))
        assert result["intent"] == "recommendation"

    def test_history(self) -> None:
        state = {"messages": [HumanMessage(content="what have I been listening to?")]}
        result = _run(_classify_intent_node(state))
        assert result["intent"] == "history"

    def test_chit_chat(self) -> None:
        state = {"messages": [HumanMessage(content="hello!")]}
        result = _run(_classify_intent_node(state))
        assert result["intent"] == "chit_chat"

    def test_extracts_entities(self) -> None:
        state = {"messages": [HumanMessage(content="suggest chill 80s tracks")]}
        result = _run(_classify_intent_node(state))
        assert "mood" in result["entities"]
        assert "time_period" in result["entities"]

    def test_backward_compat_messages_only_state(self) -> None:
        """AgentState with only messages still works."""
        state = {"messages": [HumanMessage(content="hello")]}
        result = _run(_classify_intent_node(state))
        assert result["intent"] == "chit_chat"


# =============================================================================
# route_after_classify tests
# =============================================================================


class TestRouteAfterClassify:
    def test_low_confidence_routes_to_clarify(self) -> None:
        state = {"intent": "artist_info", "intent_confidence": 0.1}
        assert _route_after_classify(state) == "clarify_or_proceed"

    def test_high_confidence_routes_to_rewrite(self) -> None:
        state = {"intent": "artist_info", "intent_confidence": 0.8}
        assert _route_after_classify(state) == "rewrite_query"

    def test_at_threshold_routes_to_rewrite(self) -> None:
        state = {"intent": "recommendation", "intent_confidence": 0.4}
        assert _route_after_classify(state) == "rewrite_query"

    def test_chit_chat_always_proceeds(self) -> None:
        state = {"intent": "chit_chat", "intent_confidence": 0.1}
        assert _route_after_classify(state) == "rewrite_query"

    def test_missing_fields_default_to_clarify(self) -> None:
        """Empty state → confidence 0.0 → clarify."""
        state: dict = {}
        assert _route_after_classify(state) == "clarify_or_proceed"


# =============================================================================
# clarify_or_proceed tests
# =============================================================================


class TestClarifyOrProceed:
    def test_returns_ai_message(self) -> None:
        state = {
            "messages": [HumanMessage(content="something")],
            "intent": "unknown",
            "intent_confidence": 0.1,
        }
        result = _run(_clarify_or_proceed(state))
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert "clarify" in result["messages"][0].content.lower()

    def test_includes_entities_in_hint(self) -> None:
        state = {
            "messages": [HumanMessage(content="chill stuff")],
            "intent": "unknown",
            "intent_confidence": 0.1,
            "entities": {"mood": ["chill"]},
        }
        result = _run(_clarify_or_proceed(state))
        content = result["messages"][0].content
        assert "chill" in content

    def test_no_entities_no_hint(self) -> None:
        state = {
            "messages": [HumanMessage(content="asdfghjkl")],
            "intent": "unknown",
            "intent_confidence": 0.1,
            "entities": {},
        }
        result = _run(_clarify_or_proceed(state))
        content = result["messages"][0].content
        assert "interested in" not in content


# ---------------------------------------------------------------------------
# Replicated rewrite_query (avoids DuckDB import chain)
# ---------------------------------------------------------------------------

_COREFERENCE_SIGNALS = [
    " it ", " they ", " them ", " that ", " this ",
    "the artist", "the band", "the song", " their ",
]


async def _rewrite_query(state: dict, *, llm_invoke: AsyncMock | None = None) -> dict:
    """Replicated from agent.graph_nodes.rewrite_query.

    Accepts an optional ``llm_invoke`` callable to avoid real LLM calls.
    """
    messages = state.get("messages", [])
    if len(messages) <= 1:
        return {}

    query = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            query = str(msg.content)
            break

    padded = f" {query.lower()} "
    if not any(signal in padded for signal in _COREFERENCE_SIGNALS):
        return {}

    # Build prompt and call LLM
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
    response = await llm_invoke([HumanMessage(content=prompt)])
    rewritten = str(response.content).strip()

    new_messages = list(messages[:-1]) + [HumanMessage(content=rewritten)]
    return {"messages": new_messages}


# =============================================================================
# rewrite_query tests
# =============================================================================


class TestRewriteQuery:
    def test_single_turn_passthrough(self) -> None:
        """Single message → no rewrite needed."""
        state = {"messages": [HumanMessage(content="who is Aphex Twin?")]}
        result = _run(_rewrite_query(state))
        assert result == {}

    def test_no_coreference_passthrough(self) -> None:
        """Multi-turn but no pronouns → no rewrite."""
        state = {
            "messages": [
                HumanMessage(content="who is Aphex Twin?"),
                AIMessage(content="Aphex Twin is a musician."),
                HumanMessage(content="what genre is zouk?"),
            ],
        }
        result = _run(_rewrite_query(state))
        assert result == {}

    def test_fires_on_pronoun(self) -> None:
        """Multi-turn with pronoun → calls LLM and rewrites."""
        mock_response = AIMessage(content="Tell me more about Aphex Twin")
        mock_invoke = AsyncMock(return_value=mock_response)

        state = {
            "messages": [
                HumanMessage(content="who is Aphex Twin?"),
                AIMessage(content="Aphex Twin is an electronic musician."),
                HumanMessage(content="tell me more about them"),
            ],
        }
        result = _run(_rewrite_query(state, llm_invoke=mock_invoke))

        # LLM was called
        mock_invoke.assert_awaited_once()

        # Last message replaced with rewritten query
        assert "messages" in result
        last_msg = result["messages"][-1]
        assert isinstance(last_msg, HumanMessage)
        assert last_msg.content == "Tell me more about Aphex Twin"

        # History preserved (original messages minus last)
        assert len(result["messages"]) == 3  # 2 original + 1 rewritten


# ---------------------------------------------------------------------------
# Replicated validate_tool_output (avoids DuckDB import chain)
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


async def _validate_tool_output(state: dict, *, max_retries: int = 1) -> dict:
    """Replicated from agent.validation.validate_tool_output."""
    messages = state.get("messages", [])
    intent = state.get("intent", "")
    entities = state.get("entities", {})
    retries = state.get("tool_validation_retries", 0)

    tool_messages = []
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "tool":
            tool_messages.append(msg)
        elif tool_messages:
            break

    if not tool_messages:
        return {}

    issues: list[str] = []

    for tool_msg in tool_messages:
        content = str(tool_msg.content).lower()
        if not content.strip():
            issues.append("Tool returned empty output.")
        elif any(signal in content for signal in _ERROR_SIGNALS):
            issues.append(f"Tool may have failed: {str(tool_msg.content)[:100]}")

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

    if not issues or retries >= max_retries:
        return {}

    hint = (
        f"[Validation] The previous tool output may not fully address the query. "
        f"Issues: {'; '.join(issues)} "
        f"Consider using a different tool or approach."
    )
    return {
        "messages": [SystemMessage(content=hint)],
        "tool_validation_retries": retries + 1,
    }


# =============================================================================
# validate_tool_output tests
# =============================================================================


class TestValidateToolOutput:
    def test_passes_on_good_output(self) -> None:
        """Non-empty, aligned tool output → passes through."""
        state = {
            "messages": [
                HumanMessage(content="who is Aphex Twin?"),
                AIMessage(content="", additional_kwargs={"tool_calls": []}),
                ToolMessage(
                    content="Aphex Twin is an electronic musician from Cornwall.",
                    tool_call_id="call_1",
                    name="get_artist_context",
                ),
            ],
            "intent": "artist_info",
            "entities": {},
            "tool_validation_retries": 0,
        }
        result = _run(_validate_tool_output(state))
        assert result == {}

    def test_catches_empty_output(self) -> None:
        """Empty tool message → corrective hint."""
        state = {
            "messages": [
                HumanMessage(content="who is Aphex Twin?"),
                ToolMessage(content="", tool_call_id="call_1", name="get_artist_context"),
            ],
            "intent": "artist_info",
            "entities": {},
            "tool_validation_retries": 0,
        }
        result = _run(_validate_tool_output(state))
        assert "messages" in result
        assert isinstance(result["messages"][0], SystemMessage)
        assert "[Validation]" in result["messages"][0].content
        assert result["tool_validation_retries"] == 1

    def test_catches_error_signal(self) -> None:
        """Tool output with error signal → corrective hint."""
        state = {
            "messages": [
                HumanMessage(content="who is Aphex Twin?"),
                ToolMessage(
                    content="Artist not found in database",
                    tool_call_id="call_1",
                    name="get_artist_context",
                ),
            ],
            "intent": "artist_info",
            "entities": {},
            "tool_validation_retries": 0,
        }
        result = _run(_validate_tool_output(state))
        assert "messages" in result
        assert "failed" in result["messages"][0].content.lower() or "Validation" in result["messages"][0].content

    def test_catches_intent_misalignment(self) -> None:
        """Intent=recommendation but tool=get_artist_context → flagged."""
        state = {
            "messages": [
                HumanMessage(content="recommend tracks like Radiohead"),
                ToolMessage(
                    content="Radiohead is a band from Oxford.",
                    tool_call_id="call_1",
                    name="get_artist_context",
                ),
            ],
            "intent": "recommendation",
            "entities": {},
            "tool_validation_retries": 0,
        }
        result = _run(_validate_tool_output(state))
        assert "messages" in result
        assert "Intent" in result["messages"][0].content or "intent" in result["messages"][0].content.lower()

    def test_respects_retry_cap(self) -> None:
        """Retries >= max → passes through even with issues."""
        state = {
            "messages": [
                HumanMessage(content="who is Aphex Twin?"),
                ToolMessage(content="", tool_call_id="call_1", name="get_artist_context"),
            ],
            "intent": "artist_info",
            "entities": {},
            "tool_validation_retries": 1,  # already at max
        }
        result = _run(_validate_tool_output(state, max_retries=1))
        assert result == {}

    def test_no_tool_messages_passthrough(self) -> None:
        """No tool messages → passes through."""
        state = {
            "messages": [HumanMessage(content="hello")],
            "intent": "chit_chat",
            "entities": {},
            "tool_validation_retries": 0,
        }
        result = _run(_validate_tool_output(state))
        assert result == {}
