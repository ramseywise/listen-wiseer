"""
``/api/chat`` + ``/api/chat/resume`` — the LangGraph agent over Server-Sent Events.

Each SSE frame is ``data: <ChatEvent json>\\n\\n``. A turn streams:
``thread`` → ``token``* (the agent node's LLM output, live) → ``tracks`` → ``suggestions``
→ ``done`` (final full text; the UI replaces the streamed text with it). A playlist save
stops at ``interrupt`` instead; ``/api/chat/resume`` answers it on the same thread.
Failures become one ``error`` event — the HTTP status is already 200 once streaming starts.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from agent.dependencies import get_checkpointer, shutdown_checkpointer
from agent.graph import RECURSION_LIMIT, build_graph
from agent.memory_store import get_store, shutdown_store
from agent.optimizer import schedule_optimization
from api.deps import Subsonic
from api.playable import Cache, ChatTrack, FallbackDep, resolve_many
from sources.schemas import TrackRef
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["chat"])

MAX_TRACKS = 25  # cards per turn; each one is a library match (+ maybe a preview lookup)
MAX_UP_NEXT = 5
_STREAM_NODE = "agent"  # the node whose LLM writes the user-facing answer
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TrackBrief(_Camel):
    artist: str
    title: str
    album: str | None = None


class ChatRequest(_Camel):
    thread_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    now_playing: TrackBrief | None = None
    up_next: list[TrackBrief] = Field(default_factory=list)


class ResumeRequest(_Camel):
    thread_id: str = Field(min_length=1)
    confirmed: bool


# ── Runtime: one compiled graph per process ──────────────────────────────────


@dataclass
class ChatRuntime:
    graph: CompiledStateGraph  # type: ignore[type-arg]
    store: BaseStore | None = None


async def build_runtime() -> ChatRuntime:
    """Same checkpointer + store setup the retired Chainlit app had (Postgres / Redis / memory)."""
    checkpointer = await get_checkpointer()
    store = await get_store()
    graph = build_graph(checkpointer=checkpointer, store=store)
    log.info("api.chat.graph_built")
    return ChatRuntime(graph=graph, store=store)


async def close_runtime() -> None:
    await shutdown_checkpointer()
    await shutdown_store()


_build_lock = asyncio.Lock()


async def get_runtime(request: Request) -> ChatRuntime:
    """Built in the app lifespan; lazily here when an app was created without it."""
    runtime: ChatRuntime | None = getattr(request.app.state, "chat_runtime", None)
    if runtime is None:
        async with _build_lock:
            runtime = getattr(request.app.state, "chat_runtime", None)
            if runtime is None:
                runtime = await build_runtime()
                request.app.state.chat_runtime = runtime
    return runtime


Runtime = Annotated[ChatRuntime, Depends(get_runtime)]


# ── Helpers ──────────────────────────────────────────────────────────────────


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def player_context(now: TrackBrief | None, up_next: Sequence[TrackBrief]) -> str:
    """Short context block for the agent; '' when the player is idle."""
    lines: list[str] = []
    if now is not None:
        album = f" (from {now.album})" if now.album else ""
        lines.append(f"Now playing: {now.artist} — {now.title}{album}")
    if up_next:
        lines.append("Up next:")
        lines += [f"{i}. {t.artist} — {t.title}" for i, t in enumerate(up_next[:MAX_UP_NEXT], 1)]
    return "\n".join(lines)


def _text(msg: BaseMessage) -> str:
    """Text of a message / chunk; Anthropic sends content blocks (text / tool_use deltas)."""
    content = msg.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


def _track_refs(agent_response: dict) -> list[TrackRef]:
    """Tracks the turn surfaced (tool artifacts), then explicit plays; deduped, capped."""
    raw = [*(agent_response.get("tracks") or []), *(agent_response.get("playable") or [])]
    refs: dict[tuple[str, str], TrackRef] = {}
    for t in raw:
        if not isinstance(t, dict) or not t.get("artist") or not t.get("title"):
            continue
        key = (str(t["artist"]).casefold(), str(t["title"]).casefold())
        refs.setdefault(
            key, TrackRef(artist=t["artist"], title=t["title"], mbid=t.get("mbid") or "")
        )
    return list(refs.values())[:MAX_TRACKS]


def _config(thread_id: str) -> RunnableConfig:
    return {
        "configurable": {"thread_id": thread_id, "langgraph_user_id": _user_id()},
        "recursion_limit": RECURSION_LIMIT,
    }


def _user_id() -> str:
    # LangGraph store namespace labels can't contain "."
    return (settings.user_id or "default").replace(".", "_")


@dataclass
class _Turn:
    runtime: ChatRuntime
    thread_id: str
    state_input: dict | Command
    client: Any  # SubsonicClient
    cache: Any  # MatchCache
    fallback: Any  # Fallback


async def _stream_turn(turn: _Turn) -> AsyncIterator[str]:
    """Run one graph turn and translate it into ChatEvents."""
    yield sse({"type": "thread", "threadId": turn.thread_id})
    config = _config(turn.thread_id)
    graph = turn.runtime.graph
    streamed: list[str] = []
    last_msg_id: str | None = None
    agent_response: dict | None = None
    final_ai: AIMessage | None = None
    interrupt_value: Any = None
    try:
        async for mode, data in graph.astream(
            turn.state_input, config=config, stream_mode=["messages", "updates"]
        ):
            if mode == "messages":
                chunk, meta = cast("tuple[BaseMessage, dict[str, Any]]", data)
                if meta.get("langgraph_node") != _STREAM_NODE:
                    continue
                if not isinstance(chunk, AIMessageChunk):
                    continue
                text = _text(chunk)
                if not text:
                    continue
                if streamed and chunk.id != last_msg_id:
                    streamed.append("\n\n")  # a new LLM call (after tools / a retry)
                    yield sse({"type": "token", "text": "\n\n"})
                last_msg_id = chunk.id
                streamed.append(text)
                yield sse({"type": "token", "text": text})
            elif mode == "updates" and isinstance(data, dict):
                if "__interrupt__" in data:
                    pending = data["__interrupt__"]
                    first = pending[0] if pending else None
                    interrupt_value = getattr(first, "value", first)
                for node, update in data.items():
                    if not isinstance(update, dict):
                        continue
                    if node == "format_response" and "agent_response" in update:
                        agent_response = update["agent_response"]
                    for msg in update.get("messages") or []:
                        if isinstance(msg, AIMessage) and not msg.tool_calls:
                            final_ai = msg

        if interrupt_value is not None:
            yield sse(_interrupt_event(interrupt_value))
            return

        response = agent_response or {}
        message = response.get("message") or (_text(final_ai) if final_ai else "")
        if not streamed and message:
            yield sse({"type": "token", "text": message})  # e.g. the clarify node (no LLM)

        refs = _track_refs(response)
        if refs:
            playables = await resolve_many(
                turn.client, refs, cache=turn.cache, fallback=turn.fallback
            )
            tracks = [
                ChatTrack(artist=r.artist, title=r.title, mbid=r.mbid or None, playable=p)
                for r, p in zip(refs, playables, strict=True)
            ]
            yield sse(
                {
                    "type": "tracks",
                    "tracks": [t.model_dump(by_alias=True, exclude_none=True) for t in tracks],
                }
            )
        suggestions = [s for s in response.get("suggestions") or [] if isinstance(s, str)]
        if suggestions:
            yield sse({"type": "suggestions", "items": suggestions[:3]})
        yield sse({"type": "done", "message": message})

        if turn.runtime.store is not None:
            snapshot = await graph.aget_state(config)
            schedule_optimization(
                _user_id(), snapshot.values.get("messages", []), turn.runtime.store
            )
    except Exception as exc:  # noqa: BLE001 — any failure must reach the client as an event
        log.error(
            "api.chat.failed",
            thread_id=turn.thread_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        yield sse({"type": "error", "detail": "Something went wrong — please try again."})


def _interrupt_event(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("type") == "confirm_playlist_create":
        return {
            "type": "interrupt",
            "kind": "confirm_playlist_create",
            "name": str(value.get("name", "")),
            "trackCount": int(value.get("track_count", 0)),
        }
    log.warning("api.chat.unknown_interrupt", value=str(value)[:200])
    return {"type": "interrupt", "kind": "confirm_playlist_create", "name": "", "trackCount": 0}


def _sse_response(events: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(events, media_type="text/event-stream", headers=_SSE_HEADERS)


# ── Routes ───────────────────────────────────────────────────────────────────


@router.post("/chat")
async def chat(
    body: ChatRequest, runtime: Runtime, client: Subsonic, cache: Cache, fallback: FallbackDep
) -> StreamingResponse:
    thread_id = body.thread_id or str(uuid.uuid4())
    log.info("api.chat.turn", thread_id=thread_id, new_thread=body.thread_id is None)
    state_input = {
        "messages": [HumanMessage(content=body.message)],
        # always set, so last turn's context doesn't linger once the player stops
        "player_context": player_context(body.now_playing, body.up_next),
    }
    turn = _Turn(runtime, thread_id, state_input, client, cache, fallback)
    return _sse_response(_stream_turn(turn))


@router.post("/chat/resume")
async def resume(
    body: ResumeRequest, runtime: Runtime, client: Subsonic, cache: Cache, fallback: FallbackDep
) -> StreamingResponse:
    log.info("api.chat.resume", thread_id=body.thread_id, confirmed=body.confirmed)
    snapshot = await runtime.graph.aget_state(_config(body.thread_id))
    if not snapshot.interrupts:

        async def nothing_pending() -> AsyncIterator[str]:
            yield sse({"type": "thread", "threadId": body.thread_id})
            yield sse({"type": "error", "detail": "Nothing is waiting for confirmation."})

        return _sse_response(nothing_pending())
    turn = _Turn(runtime, body.thread_id, Command(resume=body.confirmed), client, cache, fallback)
    return _sse_response(_stream_turn(turn))
