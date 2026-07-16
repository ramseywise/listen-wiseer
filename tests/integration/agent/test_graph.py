"""Unit tests for the LangGraph ReAct agent graph.

All tests mock the LLM and engine — no Anthropic API calls or pkl loads.
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage
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

_TRACK_RESULT = RecommendResult(
    track_uris=["spotify:track:a1"],
    track_ids=["a1"],
    track_names=["Track A"],
    scores=[0.95],
    pipeline_used="track",
    explanation="Found 1 similar track",
)


def _make_engine_mock() -> MagicMock:
    """Create an engine mock that returns proper RecommendResult by request_type."""
    engine = MagicMock()

    def _recommend(req):
        if req.request_type == "genre":
            return _GENRE_RESULT
        return _TRACK_RESULT

    engine.recommend.side_effect = _recommend
    return engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_fresh_graph():
    """Build a fresh graph instance (avoids shared MemorySaver state)."""
    import agent.graph as graph_mod

    importlib.reload(graph_mod)
    return graph_mod.build_graph()


def _config(thread_id: str) -> dict:
    """Build invocation config with thread_id and recursion_limit."""
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 20,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("agent.tools._engine", _make_engine_mock())
@patch("agent.graph_nodes._llm_with_tools")
def test_graph_direct_response(mock_llm: MagicMock) -> None:
    """No tool_calls → straight to END."""
    mock_llm.ainvoke.return_value = AIMessage(content="Hello! How can I help?")

    graph = _build_fresh_graph()
    result = graph.invoke(
        {"messages": [HumanMessage(content="hello")]},
        config=_config("test-direct"),
    )

    assert result["messages"][-1].content == "Hello! How can I help?"
    mock_llm.ainvoke.assert_called_once()


@patch("agent.tools._engine", _make_engine_mock())
@patch("agent.graph_nodes._llm_with_tools")
def test_graph_tool_then_response(mock_llm: MagicMock) -> None:
    """tool_calls → call_tools → agent → END (one loop iteration)."""
    tool_call = {
        "name": "recommend_by_genre",
        "args": {"genre_name": "zouk", "k": 5},
        "id": "tc1",
        "type": "tool_call",
    }
    ai_with_tools = AIMessage(content="", tool_calls=[tool_call])
    ai_final = AIMessage(content="Here are your zouk recommendations.")

    mock_llm.ainvoke.side_effect = [ai_with_tools, ai_final]

    graph = _build_fresh_graph()
    result = graph.invoke(
        {"messages": [HumanMessage(content="recommend zouk tracks")]},
        config=_config("test-tool"),
    )

    assert result["messages"][-1].content == "Here are your zouk recommendations."
    assert mock_llm.ainvoke.call_count == 2


@patch("agent.tools._get_client")
@patch("agent.tools._engine", _make_engine_mock())
@patch("agent.graph_nodes._llm_with_tools")
def test_graph_multi_tool_chain(
    mock_llm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Agent calls search_tracks then recommend_similar_tracks (two loop iterations)."""
    # Mock Spotify client for search_tracks
    mock_client = MagicMock()
    mock_client.search.return_value = {
        "tracks": {
            "items": [
                {
                    "name": "Creep",
                    "artists": [{"name": "Radiohead"}],
                    "id": "radio123",
                },
            ],
        },
    }
    mock_get_client.return_value = mock_client

    # Iteration 1: search
    search_call = {
        "name": "search_tracks",
        "args": {"query": "Radiohead Creep"},
        "id": "tc1",
        "type": "tool_call",
    }
    ai_search = AIMessage(content="", tool_calls=[search_call])

    # Iteration 2: recommend
    rec_call = {
        "name": "recommend_similar_tracks",
        "args": {"track_id": "radio123"},
        "id": "tc2",
        "type": "tool_call",
    }
    ai_rec = AIMessage(content="", tool_calls=[rec_call])

    # Iteration 3: final answer
    ai_final = AIMessage(content="Based on Radiohead's Creep, here are similar tracks.")

    mock_llm.ainvoke.side_effect = [ai_search, ai_rec, ai_final]

    graph = _build_fresh_graph()
    result = graph.invoke(
        {"messages": [HumanMessage(content="find tracks like Radiohead Creep")]},
        config=_config("test-chain"),
    )

    assert mock_llm.ainvoke.call_count == 3
    final_content = result["messages"][-1].content
    assert "Creep" in final_content or "similar" in final_content


@patch("agent.tools._engine", _make_engine_mock())
@patch("agent.graph_nodes._llm_with_tools")
def test_graph_multiturn_memory(mock_llm: MagicMock) -> None:
    """Two invocations with the same thread_id share message history."""
    mock_llm.ainvoke.side_effect = [
        AIMessage(content="I like zouk too!"),
        AIMessage(content="Sure, here are more zouk tracks."),
    ]

    graph = _build_fresh_graph()
    thread_id = "test-multiturn"

    # Turn 1
    result1 = graph.invoke(
        {"messages": [HumanMessage(content="I love zouk")]},
        config=_config(thread_id),
    )
    assert result1["messages"][-1].content == "I like zouk too!"

    # Turn 2 — same thread
    result2 = graph.invoke(
        {"messages": [HumanMessage(content="give me more")]},
        config=_config(thread_id),
    )
    assert result2["messages"][-1].content == "Sure, here are more zouk tracks."
    # Second invocation sees full history: system + human1 + ai1 + human2
    second_call_messages = mock_llm.ainvoke.call_args_list[1][0][0]
    assert len(second_call_messages) >= 4


@patch("agent.tools._engine", MagicMock())
@patch("agent.graph_nodes._llm_with_tools")
def test_route_after_agent_no_tool_calls(mock_llm: MagicMock) -> None:
    """route_after_agent returns __end__ when no tool_calls."""
    from agent.graph_nodes import route_after_agent

    state: dict = {"messages": [AIMessage(content="done")]}
    assert route_after_agent(state) == "__end__"


@patch("agent.tools._engine", MagicMock())
@patch("agent.graph_nodes._llm_with_tools")
def test_route_after_agent_with_tool_calls(mock_llm: MagicMock) -> None:
    """route_after_agent returns call_tools when tool_calls present."""
    from agent.graph_nodes import route_after_agent

    tc = {"name": "search_tracks", "args": {"query": "x"}, "id": "t1", "type": "tool_call"}
    state: dict = {"messages": [AIMessage(content="", tool_calls=[tc])]}
    assert route_after_agent(state) == "call_tools"
