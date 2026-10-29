"""Chainlit entry point for listen-wiseer.

Wires the LangGraph ReAct agent to the Chainlit UI.
Per-session thread_id via cl.user_session enables multi-turn memory.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import chainlit as cl
import duckdb
from langchain_core.messages import HumanMessage
from langgraph.store.base import BaseStore
from langgraph.types import Command

from agent.dependencies import get_checkpointer
from agent.graph import RECURSION_LIMIT, build_graph
from agent.memory_store import get_store
from agent.optimizer import schedule_optimization
from agent.tools.discover import db, format_playable, resolve_track
from library.playlists import save_playlist, to_jspf
from sources.schemas import PlayableTrack, TrackRef
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

_MAX_PLAY_ACTIONS = 5

# ---------------------------------------------------------------------------
# Lazy graph — rebuilt once on first session to inject async checkpointer + store
# ---------------------------------------------------------------------------
_graph = None
_store: BaseStore | None = None


async def _get_graph():
    global _graph, _store  # noqa: PLW0603
    if _graph is None:
        checkpointer = await get_checkpointer()
        _store = await get_store()
        _graph = build_graph(checkpointer=checkpointer, store=_store)
        log.info("app.graph_built")
    return _graph


def _playable_message(p: PlayableTrack) -> cl.Message:
    elements = []
    if p.preview_url:
        elements.append(
            cl.Audio(name=f"{p.artist} — {p.title} (30s)", url=p.preview_url, display="inline")
        )
    return cl.Message(content=format_playable(p), elements=elements)


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
            '- **Discover music** — *"find me tracks like Radiohead\'s Reckoner"*\n'
            '- **Listen** — *"play Weird Fishes"* (YouTube + 30s previews)\n'
            '- **Explore your history** — *"what have I been listening to?"*\n'
            '- **Genre deep dives** — *"tell me about the origins of bossa nova"*\n'
            '- **Save a playlist** — *"save those as a playlist"*\n\n'
            "What would you like to do?"
        ),
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    thread_id = cl.user_session.get("thread_id")
    user_id = settings.user_id or "default"
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

    elements: list = []
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
            actions = []
        else:
            agent_resp = result.get("agent_response", {})
            reply = agent_resp.get("message") or result["messages"][-1].content
            suggestions = agent_resp.get("suggestions", [])
            track_list = agent_resp.get("track_list", [])
            tracks = agent_resp.get("tracks", [])
            actions = [
                cl.Action(name="suggestion", label=s, payload={"query": s}) for s in suggestions[:3]
            ]
            if track_list:
                formatted = "\n".join(f"• {t}" for t in track_list)
                reply = f"{reply}\n\n**Tracks:**\n{formatted}"
            if tracks:
                actions += [
                    cl.Action(
                        name="play",
                        label=f"▶ {t['artist']} — {t['title']}",
                        payload={"artist": t["artist"], "title": t["title"]},
                    )
                    for t in tracks[:_MAX_PLAY_ACTIONS]
                ]
                actions.append(
                    cl.Action(
                        name="save_playlist",
                        label="💾 Save as playlist",
                        payload={"tracks": tracks},
                    )  # fmt: skip
                )
            for p in agent_resp.get("playable", []):
                if p.get("preview_url"):
                    elements.append(
                        cl.Audio(
                            name=f"{p['artist']} — {p['title']} (30s)",
                            url=p["preview_url"],
                            display="inline",
                        )
                    )
            schedule_optimization(user_id, result["messages"], _store)
    except Exception as exc:
        log.error("app.on_message.failed", error=str(exc), thread_id=thread_id)
        reply = "Something went wrong — please try again."
        actions = []

    await cl.Message(content=reply, actions=actions or None, elements=elements or None).send()


@cl.action_callback("suggestion")
async def on_suggestion_action(action: cl.Action) -> None:
    query = action.payload.get("query", "")
    if query:
        await on_message(cl.Message(content=query))


@cl.action_callback("play")
async def on_play_action(action: cl.Action) -> None:
    p = await asyncio.to_thread(resolve_track, action.payload["artist"], action.payload["title"])
    await _playable_message(p).send()


@cl.action_callback("save_playlist")
async def on_save_playlist_action(action: cl.Action) -> None:
    tracks = [TrackRef(**t) for t in action.payload.get("tracks", [])]
    res = await cl.AskUserMessage(content="Name for the playlist?", timeout=120).send()
    name = (res or {}).get("output", "").strip()
    if not name:
        await cl.Message(content="Playlist not saved.").send()
        return

    def _save() -> str:
        with db() as conn:
            return save_playlist(conn, name, tracks)

    try:
        pid = await asyncio.to_thread(_save)
    except duckdb.IOException as exc:
        log.error("app.save_playlist.failed", error=str(exc))
        await cl.Message(content="Couldn't open the library database — try again.").send()
        return
    jspf = cl.File(
        name=f"{name}.jspf",
        content=json.dumps(to_jspf(name, tracks), indent=2).encode(),
        mime="application/json",
        display="inline",
    )
    await cl.Message(
        content=f"Saved **{name}** ({len(tracks)} tracks, id `{pid}`). JSPF export:",
        elements=[jspf],
    ).send()
