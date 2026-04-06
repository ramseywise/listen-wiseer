"""LangGraph ReAct agent graph for listen-wiseer.

Graph structure:
    START -> trim_history -> classify_intent -> [route]
        -> low confidence  -> clarify_or_proceed -> END (wait for user)
        -> high confidence -> rewrite_query (coreference) -> agent (LLM + tools) -> [route]
            -> has tool_calls -> call_tools -> validate_tool_output -> agent  (loop)
            -> no tool_calls  -> END

The loop is bounded by recursion_limit from config.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.store.base import BaseStore

from agent.nodes import (
    agent_node,
    clarify_or_proceed,
    classify_intent_node,
    rewrite_query,
    route_after_agent,
    route_after_classify,
    trim_history,
    validate_tool_output,
)
from agent.state import AgentState
from agent.tools import ALL_TOOLS
from utils.config import settings

# Each ReAct iteration = agent + call_tools = 2 node invocations
RECURSION_LIMIT = settings.max_agent_iterations * 2


def build_graph(
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    store: BaseStore | None = None,
) -> CompiledStateGraph:  # type: ignore[type-arg]
    """Construct and compile the ReAct agent graph.

    Args:
        checkpointer: Persistence backend. Defaults to ``MemorySaver``.
        store: Shared key-value / vector store for memory namespaces.
    """
    builder = StateGraph(AgentState)

    builder.add_node("trim_history", trim_history)
    builder.add_node("classify_intent", classify_intent_node)
    builder.add_node("clarify_or_proceed", clarify_or_proceed)
    builder.add_node("rewrite_query", rewrite_query)
    builder.add_node("agent", agent_node)
    builder.add_node("call_tools", ToolNode(ALL_TOOLS))
    builder.add_node("validate_tool_output", validate_tool_output)

    builder.add_edge(START, "trim_history")
    builder.add_edge("trim_history", "classify_intent")
    builder.add_conditional_edges(
        "classify_intent",
        route_after_classify,
        {"clarify_or_proceed": "clarify_or_proceed", "rewrite_query": "rewrite_query"},
    )
    builder.add_edge("clarify_or_proceed", END)
    builder.add_edge("rewrite_query", "agent")
    builder.add_conditional_edges(
        "agent",
        route_after_agent,
        {"call_tools": "call_tools", "__end__": END},
    )
    builder.add_edge("call_tools", "validate_tool_output")
    builder.add_edge("validate_tool_output", "agent")  # loop back

    if checkpointer is None:
        checkpointer = MemorySaver()

    return builder.compile(
        checkpointer=checkpointer,
        store=store,
    )


# Default graph instance — used by Chainlit and smoke tests.
# For Redis-backed sessions, main.py builds a fresh graph with the async checkpointer.
graph = build_graph()
