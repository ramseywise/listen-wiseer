"""Chainlit entry point for listen-wiseer.

Wires the LangGraph ReAct agent to the Chainlit UI.
Per-session thread_id via cl.user_session enables multi-turn memory.
"""

from __future__ import annotations

import uuid

import chainlit as cl
from langchain_core.messages import HumanMessage

from agent.dependencies import get_checkpointer
from agent.graph import RECURSION_LIMIT, build_graph
from agent.memory_store import get_store
from agent.optimizer import schedule_optimization
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Lazy graph — rebuilt once on first session to inject async checkpointer + store
# ---------------------------------------------------------------------------
_graph = None


async def _get_graph():
    global _graph  # noqa: PLW0603
    if _graph is None:
        checkpointer = await get_checkpointer()
        store = get_store()
        _graph = build_graph(checkpointer=checkpointer, store=store)
        log.info("app.graph_built")
    return _graph


@cl.on_chat_start
async def start() -> None:
    thread_id = str(uuid.uuid4())
    cl.user_session.set("thread_id", thread_id)
    log.info("app.session_start", thread_id=thread_id)
    await cl.Message(
        content=(
            "Welcome to **listen-wiseer**! \U0001f3b5\n\n"
            "I can help you:\n"
            '- **Get recommendations** \u2014 *"find me tracks like bossa nova"*\n'
            '- **Explore your history** \u2014 *"what have I been listening to?"*\n'
            '- **Search Spotify** \u2014 *"search for Radiohead"*\n\n'
            "What would you like to do?"
        ),
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    thread_id = cl.user_session.get("thread_id")
    user_id = settings.spotify_user_id or "default"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "langgraph_user_id": user_id,
        },
        "recursion_limit": RECURSION_LIMIT,
    }
    state = {"messages": [HumanMessage(content=message.content)]}

    try:
        g = await _get_graph()
        result = await g.ainvoke(state, config=config)
        reply = result["messages"][-1].content

        # Background: optimize procedural prompt from conversation trajectory
        schedule_optimization(user_id, result["messages"], get_store())
    except Exception as exc:
        log.error("app.on_message.failed", error=str(exc), thread_id=thread_id)
        reply = "Something went wrong \u2014 please try again."

    await cl.Message(content=reply).send()
