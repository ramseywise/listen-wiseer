"""Tier 2 — Trajectory eval with optional LangFuse tracing.

Runs golden queries through the compiled graph with mocked tools.
Records which nodes were visited and which tools were called.
Cost-gated — requires CONFIRM_EXPENSIVE_OPS=true (LLM calls for agent_node
and rewrite_query).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage
from utils.langfuse_tracing import get_langfuse_handler
from utils.logging import get_logger

from evals.agent.cost_gate import CONFIRM_EXPENSIVE_OPS
from evals.tasks.models import AgentGoldenSample

log = get_logger(__name__)


@dataclass
class TrajectoryResult:
    """Result of a single trajectory eval run."""

    sample_id: str
    query: str
    actual_intent: str
    expected_intent: str
    tools_called: list[str]
    expected_tools: list[str]
    tool_match: bool
    intent_match: bool
    final_response: str = ""
    node_sequence: list[str] = field(default_factory=list)


def extract_tools_from_messages(messages: list[object]) -> list[str]:
    """Extract tool names from AIMessage.tool_calls in a message list."""
    tools: list[str] = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                tools.append(call["name"])
    return tools


def check_tool_match(expected: list[str], actual: list[str]) -> bool:
    """Check if actual tools are a superset of expected tools."""
    if not expected:
        return len(actual) == 0
    return set(expected).issubset(set(actual))


async def evaluate_trajectory(
    samples: list[AgentGoldenSample],
    graph: object,
    *,
    enable_tracing: bool = False,
) -> list[TrajectoryResult]:
    """Run graph on each sample and collect trajectory. Cost-gated.

    Args:
        samples: Golden samples to evaluate.
        graph: Compiled LangGraph state graph (must support ainvoke).
        enable_tracing: Attach LangFuse handler if True and configured.

    Returns:
        List of TrajectoryResult, one per sample.
    """
    if not CONFIRM_EXPENSIVE_OPS:
        raise RuntimeError("Set CONFIRM_EXPENSIVE_OPS=true env var for trajectory eval.")

    results: list[TrajectoryResult] = []

    for sample in samples:
        handler = (
            get_langfuse_handler(session_id=f"eval_traj_{sample.sample_id}")
            if enable_tracing
            else None
        )
        config: dict[str, object] = {"configurable": {"thread_id": sample.sample_id}}
        if handler:
            config["callbacks"] = [handler]

        state = {"messages": [HumanMessage(content=sample.query)]}

        try:
            result_state = await graph.ainvoke(state, config=config)  # type: ignore[union-attr]
            messages = result_state.get("messages", [])
            tools_called = extract_tools_from_messages(messages)
            actual_intent = result_state.get("intent", "unknown")
            last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
            final_response = str(last_ai.content) if last_ai else ""
        except Exception as exc:
            log.error(
                "eval.trajectory.sample_error",
                sample_id=sample.sample_id,
                error=str(exc),
            )
            tools_called = []
            actual_intent = "error"
            final_response = ""

        tool_match = check_tool_match(sample.expected_tools, tools_called)
        intent_match = actual_intent == sample.expected_intent

        results.append(
            TrajectoryResult(
                sample_id=sample.sample_id,
                query=sample.query,
                actual_intent=actual_intent,
                expected_intent=sample.expected_intent,
                tools_called=tools_called,
                expected_tools=sample.expected_tools,
                tool_match=tool_match,
                intent_match=intent_match,
                final_response=final_response,
            )
        )
        log.debug(
            "eval.trajectory.sample",
            sample_id=sample.sample_id,
            tool_match=tool_match,
            intent_match=intent_match,
        )

    n_tool_match = sum(1 for r in results if r.tool_match)
    n_intent_match = sum(1 for r in results if r.intent_match)
    log.info(
        "eval.trajectory.complete",
        n_samples=len(results),
        tool_accuracy=n_tool_match / len(results) if results else 0.0,
        intent_accuracy=n_intent_match / len(results) if results else 0.0,
    )
    return results
