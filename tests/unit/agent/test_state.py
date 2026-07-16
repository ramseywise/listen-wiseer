from __future__ import annotations

from agent.state import AgentState
from langchain_core.messages import AIMessage, HumanMessage


def test_state_construction() -> None:
    state: AgentState = {"messages": [HumanMessage(content="hello")]}
    assert len(state["messages"]) == 1
    assert state["messages"][0].content == "hello"


def test_state_empty_messages() -> None:
    state: AgentState = {"messages": []}
    assert state["messages"] == []


def test_state_multiple_message_types() -> None:
    state: AgentState = {
        "messages": [
            HumanMessage(content="recommend zouk"),
            AIMessage(content="Here are some tracks."),
        ],
    }
    assert len(state["messages"]) == 2
    assert isinstance(state["messages"][0], HumanMessage)
    assert isinstance(state["messages"][1], AIMessage)
