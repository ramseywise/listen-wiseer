"""Unit tests for the background prompt optimizer.

Mocks the langmem optimizer — no API costs. Tests trajectory shape and store update.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.store.memory import InMemoryStore
from langmem import Prompt

from agent.memory_store import get_procedural_prompt
from agent.optimizer import optimize_prompt


def _run(coro):
    """Helper to run async in sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


def test_optimizer_skips_short_conversations() -> None:
    """Conversations with < 4 messages are too short to learn from."""
    store = InMemoryStore()
    messages = [HumanMessage(content="hi"), AIMessage(content="hello")]

    _run(optimize_prompt("user1", messages, store))

    # No procedural prompt should be written
    result = _run(get_procedural_prompt("user1", store))
    assert result is None


@patch("agent.optimizer._get_optimizer")
def test_optimizer_updates_procedural_memory(mock_get_opt: MagicMock) -> None:
    """Optimizer writes new instructions to procedural memory."""
    mock_optimizer = AsyncMock()
    mock_optimizer.ainvoke.return_value = [
        Prompt(
            name="user_strategy",
            prompt="User prefers zouk and acoustic tracks. Keep recommendations under 5 items.",
        ),
    ]
    mock_get_opt.return_value = mock_optimizer

    store = InMemoryStore()
    messages = [
        HumanMessage(content="I love zouk music"),
        AIMessage(content="Great taste! Let me find some zouk tracks."),
        HumanMessage(content="Perfect, but keep the list short please"),
        AIMessage(content="Here are 3 zouk tracks: 1. A 2. B 3. C"),
    ]

    _run(optimize_prompt("user1", messages, store))

    result = _run(get_procedural_prompt("user1", store))
    assert result is not None
    assert "zouk" in result

    # Verify the optimizer was called with correct trajectory shape
    call_args = mock_optimizer.ainvoke.call_args[0][0]
    assert "trajectories" in call_args
    assert "prompts" in call_args
    assert len(call_args["trajectories"]) == 1
    assert len(call_args["prompts"]) == 1


@patch("agent.optimizer._get_optimizer")
def test_optimizer_no_change_when_instructions_unchanged(mock_get_opt: MagicMock) -> None:
    """Optimizer doesn't write if the LLM returns the same instructions."""
    existing = "User likes zouk."

    mock_optimizer = AsyncMock()
    mock_optimizer.ainvoke.return_value = [
        Prompt(name="user_strategy", prompt=existing),
    ]
    mock_get_opt.return_value = mock_optimizer

    store = InMemoryStore()
    # Pre-populate procedural memory
    _run(
        store.aput(
            ("enoa", "user1", "strategy"),
            "system_instructions",
            {"instructions": existing},
            index=False,
        )
    )

    messages = [
        HumanMessage(content="more zouk"),
        AIMessage(content="sure"),
        HumanMessage(content="thanks"),
        AIMessage(content="done"),
    ]

    _run(optimize_prompt("user1", messages, store))

    # Should still be the original
    result = _run(get_procedural_prompt("user1", store))
    assert result == existing


@patch("agent.optimizer._get_optimizer")
def test_optimizer_handles_llm_error(mock_get_opt: MagicMock) -> None:
    """Optimizer catches LLM errors without crashing."""
    mock_optimizer = AsyncMock()
    mock_optimizer.ainvoke.side_effect = RuntimeError("API down")
    mock_get_opt.return_value = mock_optimizer

    store = InMemoryStore()
    messages = [
        HumanMessage(content="test"),
        AIMessage(content="test"),
        HumanMessage(content="test"),
        AIMessage(content="test"),
    ]

    # Should not raise
    _run(optimize_prompt("user1", messages, store))

    # No procedural prompt written
    result = _run(get_procedural_prompt("user1", store))
    assert result is None
