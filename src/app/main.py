"""Chainlit entry point for listen-wiseer.

Wires the LangGraph ReAct agent to the Chainlit UI.
Per-session thread_id via cl.user_session enables multi-turn memory.
"""

from __future__ import annotations

import uuid

import chainlit as cl
from langchain_core.messages import HumanMessage

from agent.graph import RECURSION_LIMIT, graph
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)


@cl.on_chat_start
async def start() -> None:
    thread_id = str(uuid.uuid4())
    cl.user_session.set("thread_id", thread_id)
    log.info("app.session_start", thread_id=thread_id)
    await cl.Message(
        content=(
            "Welcome to **listen-wiseer**! 🎵\n\n"
            "I can help you:\n"
            '- **Get recommendations** — *"find me tracks like bossa nova"*\n'
            '- **Explore your history** — *"what have I been listening to?"*\n'
            '- **Search Spotify** — *"search for Radiohead"*\n\n'
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
        result = await graph.ainvoke(state, config=config)
        reply = result["messages"][-1].content
    except Exception as exc:
        log.error("app.on_message.failed", error=str(exc), thread_id=thread_id)
        reply = "Something went wrong — please try again."

    await cl.Message(content=reply).send()
