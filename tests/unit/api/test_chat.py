"""``/api/chat`` + ``/api/chat/resume`` — the real graph over SSE, driven by a scripted LLM.

No Anthropic calls: the agent node's model is a streaming fake; intent classification is
pinned high-confidence; tools that would hit the network / DB are patched.
"""

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import duckdb
import pytest
from fastapi.testclient import TestClient
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

import agent.tools.discover as discover_tools
from agent.graph import build_graph
from agent.intent import QueryAnalysis
from api.chat import ChatRuntime, get_runtime, player_context
from api.chat import TrackBrief as Brief
from api.playable import get_fallback, get_match_cache
from library.navidrome_playlist import SavedPlaylist
from recommend.discover import Candidate
from sources.schemas import PlayableTrack, TrackRef


class ScriptedChat(BaseChatModel):
    """Replies from a script; streams text word by word and tool calls as one chunk."""

    script: list[AIMessage]
    seen: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        self.seen.append(list(messages))
        # the last reply repeats if the graph asks again (e.g. a verifier retry)
        return self.script.pop(0) if len(self.script) > 1 else self.script[0]

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        reply = self._next(messages)
        words = str(reply.content).split(" ") if reply.content else []
        for i, word in enumerate(words):
            text = word if i == 0 else f" {word}"
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=text))
            if run_manager:
                await run_manager.on_llm_new_token(text, chunk=chunk)
            yield chunk
        if reply.tool_calls:
            tool_chunks = [
                {"name": tc["name"], "args": json.dumps(tc["args"]), "id": tc["id"], "index": n,
                 "type": "tool_call_chunk"}
                for n, tc in enumerate(reply.tool_calls)
            ]  # fmt: skip
            chunk = ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_call_chunks=tool_chunks)  # type: ignore[arg-type]
            )
            if run_manager:
                await run_manager.on_llm_new_token("", chunk=chunk)
            yield chunk


def _call(name: str, args: dict, call_id: str = "tc-1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def _analyzer(confidence: float = 0.95) -> MagicMock:
    analyzer = MagicMock()
    analyzer.analyze.return_value = QueryAnalysis(
        original_query="", intent="discover", complexity="simple", expanded_query="",
        entities={}, sub_queries=[], retrieval_mode="hybrid", confidence=confidence,
    )  # fmt: skip
    return analyzer


def _fallback(artist: str, title: str) -> PlayableTrack:
    return PlayableTrack(
        artist=artist, title=title, youtube_url="https://yt.test/w",
        preview_url="https://dz.test/p.mp3",
    )  # fmt: skip


def events(response) -> list[dict]:
    """Parse SSE frames (``data: <json>\\n\\n``)."""
    frames = [f for f in response.text.split("\n\n") if f]
    assert all(f.startswith("data: ") for f in frames), frames
    return [json.loads(f.removeprefix("data: ")) for f in frames]


def _types(evs: list[dict]) -> list[str]:
    return [e["type"] for e in evs]


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def chat_api(api: TestClient, store: InMemoryStore) -> Iterator[TestClient]:
    """API with a real graph (MemorySaver) and no network: preview fallback + DB patched."""
    runtime = ChatRuntime(graph=build_graph(checkpointer=MemorySaver(), store=store), store=store)
    app = api.app
    app.dependency_overrides[get_runtime] = lambda: runtime  # type: ignore[attr-defined]
    app.dependency_overrides[get_fallback] = lambda: _fallback  # type: ignore[attr-defined]
    app.dependency_overrides[get_match_cache] = lambda: None  # type: ignore[attr-defined]

    @contextmanager
    def locked_db():
        raise duckdb.IOException("no project DB in unit tests")
        yield

    with (
        patch("agent.graph_nodes._query_analyzer", _analyzer()),
        patch.object(discover_tools, "db", locked_db),
        patch("api.chat.schedule_optimization") as optimize,
    ):
        api.optimize = optimize  # type: ignore[attr-defined]
        yield api


@contextmanager
def scripted(*replies: AIMessage) -> Iterator[ScriptedChat]:
    llm = ScriptedChat(script=list(replies), seen=[])
    with (
        patch("agent.graph_nodes._llm_with_tools_instance", llm),
        patch("agent.graph_nodes._llm_instance", llm),
    ):
        yield llm


CANDIDATES = [
    Candidate(artist="ProleteR", title="April Showers", mbid="", score=1.0,
              sources=["lastfm"], known_artist=True),
    Candidate(artist="Radiohead", title="Reckoner", mbid="mb-1", score=0.9,
              sources=["listenbrainz"], known_artist=False),
]  # fmt: skip


def test_turn_streams_tokens_then_tracks_suggestions_done(chat_api: TestClient) -> None:
    answer = "Music like ProleteR: April Showers by ProleteR and Reckoner by Radiohead."
    with (
        scripted(_call("discover_tracks", {"artist": "ProleteR"}), AIMessage(content=answer)),
        patch.object(discover_tools, "discover", return_value=CANDIDATES),
    ):
        r = chat_api.post("/api/chat", json={"message": "music like ProleteR"})

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    evs = events(r)
    assert evs[0]["type"] == "thread" and evs[0]["threadId"]
    tokens = [e["text"] for e in evs if e["type"] == "token"]
    assert len(tokens) > 1  # streamed, not one blob
    assert "".join(tokens) == answer
    kinds = _types(evs)
    assert kinds.index("tracks") > max(i for i, k in enumerate(kinds) if k == "token")
    assert kinds[-1] == "done" and evs[-1]["message"] == answer

    [tracks_ev] = [e for e in evs if e["type"] == "tracks"]
    library, missing = tracks_ev["tracks"]
    assert library["playable"]["songId"] == "s1"
    assert library["playable"]["coverUrl"] == "/api/cover/mf-s1?size=300"
    assert missing == {
        "artist": "Radiohead",
        "title": "Reckoner",
        "mbid": "mb-1",
        "playable": {
            "artist": "Radiohead",
            "title": "Reckoner",
            "previewUrl": "https://dz.test/p.mp3",
            "youtubeUrl": "https://yt.test/w",
        },
    }
    if "suggestions" in kinds:
        [sug] = [e for e in evs if e["type"] == "suggestions"]
        assert sug["items"] and all(isinstance(s, str) for s in sug["items"])
    chat_api.optimize.assert_called_once()  # type: ignore[attr-defined]


def test_thread_id_is_kept_across_turns(chat_api: TestClient) -> None:
    with scripted(AIMessage(content="First answer."), AIMessage(content="Second answer.")) as llm:
        first = events(chat_api.post("/api/chat", json={"message": "hello there"}))
        thread_id = first[0]["threadId"]
        second = events(
            chat_api.post("/api/chat", json={"threadId": thread_id, "message": "and again"})
        )
    assert second[0] == {"type": "thread", "threadId": thread_id}
    assert second[-1] == {"type": "done", "message": "Second answer."}
    # the second LLM call saw the first turn's history
    assert any("First answer." in str(m.content) for m in llm.seen[-1])


def test_player_context_reaches_the_agent_but_not_the_history(chat_api: TestClient) -> None:
    body = {
        "message": "more like this",
        "nowPlaying": {"artist": "ProleteR", "title": "April Showers", "album": "Curbside"},
        "upNext": [{"artist": "Nujabes", "title": "Aruarian Dance"}],
    }
    with scripted(AIMessage(content="Sure.")) as llm:
        evs = events(chat_api.post("/api/chat", json=body))
    assert evs[-1]["type"] == "done"
    system = str(llm.seen[0][0].content)
    assert "Now playing: ProleteR — April Showers (from Curbside)" in system
    assert "1. Nujabes — Aruarian Dance" in system
    humans = [m for m in llm.seen[0] if m.type == "human"]
    assert [str(m.content) for m in humans] == ["more like this"]


def test_player_context_text() -> None:
    assert player_context(None, []) == ""
    up = [Brief(artist=f"A{i}", title="t") for i in range(8)]
    text = player_context(Brief(artist="X", title="Y"), up)
    assert text.splitlines()[0] == "Now playing: X — Y"
    assert text.splitlines()[-1] == "5. A4 — t"  # capped


def test_save_playlist_interrupts_then_resume_saves(chat_api: TestClient) -> None:
    tracks = [{"artist": "ProleteR", "title": "April Showers"}]
    saved = SavedPlaylist(name="Rainy", n_tracks=1, playlist_id="pl1", matched=1)
    save = MagicMock(return_value=("Saved playlist 'Rainy' (1 of 1 matched).", []))

    async def fake_save(name, refs, description=""):
        return save(name, refs, description)

    with (
        scripted(
            _call("save_playlist", {"name": "Rainy", "tracks": tracks}, "tc-save"),
            AIMessage(content="Saved it to your library."),
        ),
        patch.object(discover_tools, "save_playlist_to_library", fake_save),
    ):
        evs = events(chat_api.post("/api/chat", json={"message": "save these as Rainy"}))
        assert _types(evs) == ["thread", "interrupt"]
        assert evs[1] == {
            "type": "interrupt",
            "kind": "confirm_playlist_create",
            "name": "Rainy",
            "trackCount": 1,
        }
        save.assert_not_called()

        thread_id = evs[0]["threadId"]
        resumed = events(
            chat_api.post("/api/chat/resume", json={"threadId": thread_id, "confirmed": True})
        )
    assert resumed[0] == {"type": "thread", "threadId": thread_id}
    assert resumed[-1] == {"type": "done", "message": "Saved it to your library."}
    [(name, refs, _)] = [c.args for c in save.call_args_list]
    assert name == "Rainy" and refs == [TrackRef(artist="ProleteR", title="April Showers")]
    assert saved.playlist_id == "pl1"


def test_resume_cancel_does_not_save(chat_api: TestClient) -> None:
    tracks = [{"artist": "ProleteR", "title": "April Showers"}]
    with (
        scripted(
            _call("save_playlist", {"name": "Rainy", "tracks": tracks}, "tc-save"),
            AIMessage(content="Okay, not saved."),
        ),
        patch.object(discover_tools, "save_playlist_to_library") as save,
    ):
        evs = events(chat_api.post("/api/chat", json={"message": "save these"}))
        resumed = events(
            chat_api.post(
                "/api/chat/resume", json={"threadId": evs[0]["threadId"], "confirmed": False}
            )
        )
    save.assert_not_called()
    assert resumed[-1] == {"type": "done", "message": "Okay, not saved."}


def test_resume_without_pending_interrupt_is_an_error_event(chat_api: TestClient) -> None:
    evs = events(chat_api.post("/api/chat/resume", json={"threadId": "nope", "confirmed": True}))
    assert _types(evs) == ["thread", "error"]


def test_llm_failure_becomes_error_event(chat_api: TestClient) -> None:
    class Boom(ScriptedChat):
        def _next(self, messages: list[BaseMessage]) -> AIMessage:
            raise RuntimeError("anthropic_api_key missing")

    llm = Boom(script=[AIMessage(content="x")], seen=[])
    with patch("agent.graph_nodes._llm_with_tools_instance", llm):
        r = chat_api.post("/api/chat", json={"message": "hello"})
    assert r.status_code == 200
    evs = events(r)
    assert _types(evs) == ["thread", "error"]
    assert "anthropic" not in evs[1]["detail"].lower()  # internals stay in the log


def test_clarify_reply_is_sent_as_one_token(chat_api: TestClient) -> None:
    with (
        patch("agent.graph_nodes._query_analyzer", _analyzer(confidence=0.1)),
        scripted(AIMessage(content="unused")) as llm,
    ):
        evs = events(chat_api.post("/api/chat", json={"message": "hmm"}))
    assert llm.seen == []
    assert _types(evs) == ["thread", "token", "done"] or _types(evs) == [
        "thread", "token", "suggestions", "done",
    ]  # fmt: skip
    assert evs[1]["text"].startswith("I want to make sure I help you")
    assert evs[-1]["message"] == evs[1]["text"]


def test_empty_message_is_rejected(chat_api: TestClient) -> None:
    assert chat_api.post("/api/chat", json={"message": ""}).status_code == 422


def test_verifier_retry_streams_both_drafts_and_done_carries_the_final(
    chat_api: TestClient,
) -> None:
    final = "Rainy music like ProleteR: try April Showers."
    with scripted(AIMessage(content="Nope."), AIMessage(content=final)):
        evs = events(chat_api.post("/api/chat", json={"message": "rainy music like ProleteR"}))
    streamed = "".join(e["text"] for e in evs if e["type"] == "token")
    assert streamed == f"Nope.\n\n{final}"  # the UI swaps in done.message
    assert evs[-1] == {"type": "done", "message": final}
