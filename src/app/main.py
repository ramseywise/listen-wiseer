"""Chainlit entry point for listen-wiseer.

Wires the LangGraph ReAct agent to the Chainlit UI.
Per-session thread_id via cl.user_session enables multi-turn memory.
"""

from __future__ import annotations

import uuid

import chainlit as cl
from langchain_core.messages import HumanMessage
from langgraph.types import Command

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
        store = await get_store()
        _graph = build_graph(checkpointer=checkpointer, store=store)
        log.info("app.graph_built")
    return _graph


@cl.on_chat_start
async def start() -> None:
    thread_id = str(uuid.uuid4())
    cl.user_session.set("thread_id", thread_id)
    cl.user_session.set("awaiting_confirm", None)
    log.info("app.session_start", thread_id=thread_id)
    await cl.Message(
        content=(
            "Welcome to **listen-wiseer**! \U0001f3b5\n\n"
            "I can help you:\n"
            '- **Get recommendations** — *"find me tracks like bossa nova"*\n'
            '- **Explore your history** — *"what have I been listening to?"*\n'
            '- **Explore your taste** — *"how has my music taste changed over time?"*\n'
            '- **Genre deep dives** — *"tell me about the origins of bossa nova"*\n'
            '- **Search Spotify** — *"search for Radiohead"*\n'
            '- **Save a playlist** — *"create a playlist from those tracks"*\n\n'
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

    # Resume from playlist confirmation interrupt if pending
    awaiting = cl.user_session.get("awaiting_confirm")
    if awaiting:
        cl.user_session.set("awaiting_confirm", None)
        confirmed = message.content.strip().lower() in {"yes", "y", "confirm", "ok", "sure", "yep"}
        state_input: dict | Command = Command(resume=confirmed)
    else:
        state_input = {"messages": [HumanMessage(content=message.content)]}

    try:
        g = await _get_graph()
        result = await g.ainvoke(state_input, config=config)

        # Check for HITL interrupt (playlist write confirmation)
        interrupts = result.get("__interrupt__")
        if interrupts:
            interrupt_val = (
                interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
            )
            cl.user_session.set("awaiting_confirm", interrupt_val)
            if (
                isinstance(interrupt_val, dict)
                and interrupt_val.get("type") == "confirm_playlist_create"
            ):
                name = interrupt_val["name"]
                count = interrupt_val["track_count"]
                reply = (
                    f"Ready to create playlist **{name}** with **{count} tracks**.\n\n"
                    "Confirm? Reply **yes** to save or **no** to cancel."
                )
            else:
                reply = "Awaiting your confirmation. Reply **yes** to proceed or **no** to cancel."
        else:
            agent_resp = result.get("agent_response", {})
            reply = agent_resp.get("message") or result["messages"][-1].content
            suggestions = agent_resp.get("suggestions", [])
            track_list = agent_resp.get("track_list", [])
            actions = [
                cl.Action(name="suggestion", label=s, payload={"query": s}) for s in suggestions[:3]
            ]
            if track_list:
                formatted = "\n".join(f"• {t}" for t in track_list)
                reply = f"{reply}\n\n**Tracks:**\n{formatted}"
            schedule_optimization(user_id, result["messages"], get_store())
    except Exception as exc:
        log.error("app.on_message.failed", error=str(exc), thread_id=thread_id)
        reply = "Something went wrong — please try again."
        actions = []

    await cl.Message(content=reply, actions=actions or None).send()


@cl.action_callback("suggestion")
async def on_suggestion_action(action: cl.Action) -> None:
    query = action.payload.get("query", "")
    if query:
        await on_message(cl.Message(content=query))
