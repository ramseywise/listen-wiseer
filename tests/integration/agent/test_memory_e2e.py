"""End-to-end integration tests for the memory layer.

These exercise the real InMemoryStore + graph wiring with a mocked LLM
and engine. No Spotify, DuckDB, or API calls required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.store.memory import InMemoryStore

from recommend.schemas import RecommendResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_GENRE_RESULT = RecommendResult(
    track_uris=["spotify:track:z1", "spotify:track:z2"],
    track_ids=["z1", "z2"],
    track_names=["Zouk Night", "Zouk Morning"],
    scores=[0.9, 0.8],
    pipeline_used="genre",
    explanation="Found 2 zouk tracks",
)


def _make_engine_mock() -> MagicMock:
    engine = MagicMock()
    engine.recommend.return_value = _GENRE_RESULT
    return engine


def _build_graph_with_store(store: InMemoryStore):
    """Build a fresh graph with the given store."""
    from agent.graph import build_graph

    return build_graph(store=store)


def _config(thread_id: str, user_id: str = "test-user") -> dict:
    return {
        "configurable": {
            "thread_id": thread_id,
            "langgraph_user_id": user_id,
        },
        "recursion_limit": 20,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@patch("agent.tools._engine", _make_engine_mock())
@patch("agent.graph_nodes._llm_with_tools", new_callable=AsyncMock)
async def test_taste_memory_roundtrip(mock_llm: AsyncMock) -> None:
    """manage_taste_memory stores a fact, search_taste_memory retrieves it."""
    store = InMemoryStore()
    graph = _build_graph_with_store(store)

    # Step 1: Agent calls manage_taste_memory
    manage_call = {
        "name": "manage_taste_memory",
        "args": {"content": "User loves zouk and bossa nova", "action": "create"},
        "id": "tc1",
        "type": "tool_call",
    }
    ai_manage = AIMessage(content="", tool_calls=[manage_call])

    # Step 2: Agent calls search_taste_memory
    search_call = {
        "name": "search_taste_memory",
        "args": {"query": "zouk"},
        "id": "tc2",
        "type": "tool_call",
    }
    ai_search = AIMessage(content="", tool_calls=[search_call])

    # Step 3: Agent gives final answer
    ai_final = AIMessage(content="You love zouk and bossa nova!")

    mock_llm.ainvoke.side_effect = [ai_manage, ai_search, ai_final]

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="remember I love zouk")]},
        config=_config("taste-roundtrip"),
    )

    assert result["messages"][-1].content == "You love zouk and bossa nova!"

    # Verify store has the fact
    items = store.search(("enoa", "test-user", "taste"))
    assert len(items) >= 1
    contents = [item.value.get("content", "") for item in items]
    assert any("zouk" in c for c in contents)


@pytest.mark.integration
@patch("agent.tools._engine", _make_engine_mock())
@patch("agent.graph_nodes._llm_with_tools", new_callable=AsyncMock)
async def test_episodic_session_stored_after_recommendation(mock_llm: AsyncMock) -> None:
    """After a recommendation, episodic memory stores the session."""
    store = InMemoryStore()
    graph = _build_graph_with_store(store)

    # Agent returns a recommendation-shaped response (numbered list)
    ai_final = AIMessage(content="Here are your recommendations:\n1. Zouk Night\n2. Zouk Morning")
    mock_llm.ainvoke.return_value = ai_final

    await graph.ainvoke(
        {"messages": [HumanMessage(content="recommend me some zouk")]},
        config=_config("episodic-store"),
    )

    # Check episodic memory was populated
    items = store.search(("enoa", "test-user", "sessions"))
    assert len(items) >= 1
    assert "zouk" in items[0].value.get("request", "").lower()


@pytest.mark.integration
@patch("agent.tools._engine", _make_engine_mock())
@patch("agent.graph_nodes._llm_with_tools", new_callable=AsyncMock)
async def test_memory_stats_populated(mock_llm: AsyncMock) -> None:
    """When store has data, memory_stats block appears in the system prompt."""
    store = InMemoryStore()

    # Pre-populate store
    store.put(
        ("enoa", "test-user", "sessions"),
        "s1",
        {"request": "zouk", "tracks": "1. ZoukA"},
    )
    store.put(
        ("enoa", "test-user", "taste"),
        "t1",
        {"content": "loves zouk"},
    )

    graph = _build_graph_with_store(store)

    ai_final = AIMessage(content="Hi there!")
    mock_llm.ainvoke.return_value = ai_final

    await graph.ainvoke(
        {"messages": [HumanMessage(content="hello")]},
        config=_config("stats-test"),
    )

    # Inspect the system prompt passed to the LLM
    call_args = mock_llm.ainvoke.call_args[0][0]
    system_content = call_args[0].content
    assert "<memory_stats>" in system_content
    assert "Past sessions on record: 1" in system_content
    assert "Taste facts stored: 1" in system_content
