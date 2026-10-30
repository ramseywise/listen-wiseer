"""Unit tests for agent.graph wiring — compile, node set, and route table.

No LLM calls: only graph construction and the pure routing functions.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from agent.graph import RECURSION_LIMIT, build_graph
from agent.graph_nodes import route_after_agent, route_after_classify, route_after_verify
from utils.config import settings

_EXPECTED_NODES = {
    "trim_history",
    "classify_intent",
    "clarify_or_proceed",
    "rewrite_query",
    "agent",
    "call_tools",
    "validate_tool_output",
    "format_response",
    "verify_answer",
}


def _edges(graph) -> set[tuple[str, str]]:
    return {(e.source, e.target) for e in graph.get_graph().edges}


class TestBuildGraph:
    def test_compiles_with_memory_saver_and_store(self) -> None:
        saver, store = MemorySaver(), InMemoryStore()
        graph = build_graph(checkpointer=saver, store=store)
        assert graph.checkpointer is saver
        assert graph.store is store

    def test_defaults_to_memory_saver(self) -> None:
        assert isinstance(build_graph().checkpointer, MemorySaver)

    def test_has_expected_nodes(self) -> None:
        nodes = set(build_graph().get_graph().nodes) - {"__start__", "__end__"}
        assert nodes == _EXPECTED_NODES

    def test_edges_form_react_and_verify_loops(self) -> None:
        edges = _edges(build_graph())
        assert {
            ("__start__", "trim_history"),
            ("trim_history", "classify_intent"),
            ("classify_intent", "clarify_or_proceed"),
            ("classify_intent", "rewrite_query"),
            ("clarify_or_proceed", "__end__"),
            ("rewrite_query", "agent"),
            ("agent", "call_tools"),
            ("agent", "format_response"),
            ("call_tools", "validate_tool_output"),
            ("validate_tool_output", "agent"),
            ("format_response", "verify_answer"),
            ("verify_answer", "agent"),
            ("verify_answer", "__end__"),
        } <= edges

    def test_recursion_limit_covers_agent_iterations(self) -> None:
        assert RECURSION_LIMIT == settings.max_agent_iterations * 2


class TestRouteAfterClassify:
    def test_low_confidence_clarifies(self) -> None:
        state = {"intent": "recommendation", "intent_confidence": 0.0}
        assert route_after_classify(state) == "clarify_or_proceed"  # type: ignore[arg-type]

    def test_high_confidence_proceeds(self) -> None:
        state = {"intent": "recommendation", "intent_confidence": 1.0}
        assert route_after_classify(state) == "rewrite_query"  # type: ignore[arg-type]

    def test_chit_chat_never_clarifies(self) -> None:
        state = {"intent": "chit_chat", "intent_confidence": 0.0}
        assert route_after_classify(state) == "rewrite_query"  # type: ignore[arg-type]

    def test_missing_confidence_clarifies(self) -> None:
        assert route_after_classify({}) == "clarify_or_proceed"  # type: ignore[arg-type]


class TestRouteAfterAgent:
    def test_tool_calls_route_to_tools(self) -> None:
        msg = AIMessage(content="", tool_calls=[{"name": "search_tracks", "args": {}, "id": "t1"}])
        assert route_after_agent({"messages": [msg]}) == "call_tools"  # type: ignore[arg-type]

    def test_plain_answer_routes_to_format(self) -> None:
        state = {"messages": [AIMessage(content="done")]}
        assert route_after_agent(state) == "format_response"  # type: ignore[arg-type]

    def test_empty_messages_route_to_format(self) -> None:
        assert route_after_agent({"messages": []}) == "format_response"  # type: ignore[arg-type]


class TestRouteAfterVerify:
    @pytest.fixture(autouse=True)
    def _two_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "max_verification_retries", 2)

    def test_critique_with_retries_left_loops_to_agent(self) -> None:
        state = {
            "checker_critique": "too vague",
            "verification_retries": 1,
            "messages": [HumanMessage(content="critique: be specific")],
        }
        assert route_after_verify(state) == "agent"  # type: ignore[arg-type]

    def test_retries_exhausted_ends(self) -> None:
        state = {
            "checker_critique": "too vague",
            "verification_retries": 3,
            "messages": [HumanMessage(content="critique")],
        }
        assert route_after_verify(state) == "END"  # type: ignore[arg-type]

    def test_no_critique_ends(self) -> None:
        state = {"checker_critique": "", "messages": [AIMessage(content="ok")]}
        assert route_after_verify(state) == "END"  # type: ignore[arg-type]

    def test_critique_without_injected_human_message_ends(self) -> None:
        state = {"checker_critique": "x", "messages": [AIMessage(content="answer")]}
        assert route_after_verify(state) == "END"  # type: ignore[arg-type]
