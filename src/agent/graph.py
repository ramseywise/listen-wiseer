"""LangGraph ReAct agent graph for listen-wiseer.

Graph structure:
    START → agent (LLM + tools) → [route]
        → has tool_calls → call_tools (ToolNode) → agent  (loop)
        → no tool_calls  → END

The loop is bounded by recursion_limit passed at invocation time.
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from agent.nodes import agent_node, route_after_agent
from agent.state import AgentState
from agent.tools import ALL_TOOLS
from utils.config import settings

# Each ReAct iteration = agent + call_tools = 2 node invocations
RECURSION_LIMIT = settings.max_agent_iterations * 2


def build_graph() -> CompiledStateGraph:  # type: ignore[type-arg]
    """Construct and compile the ReAct agent graph."""
    builder = StateGraph(AgentState)

    builder.add_node("agent", agent_node)
    builder.add_node("call_tools", ToolNode(ALL_TOOLS))

    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        route_after_agent,
        {"call_tools": "call_tools", "__end__": END},
    )
    builder.add_edge("call_tools", "agent")  # loop back

    memory = MemorySaver()
    return builder.compile(checkpointer=memory)


graph = build_graph()
