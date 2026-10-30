"""Scripted-LLM integration test for the save_playlist HITL interrupt → resume path.

The graph runs end to end with a fake tool-calling LLM; ``save_playlist`` hits
``interrupt()`` and is resumed with ``Command(resume=...)`` exactly as
``api/chat.py`` does. On approval the playlist goes to a fake Navidrome (D2); DuckDB and
the JSPF export dir are redirected to tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import duckdb
import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from agent.intent import QueryAnalysis
from sources.subsonic import SubsonicClient

pytestmark = pytest.mark.integration  # self-contained: tmp DuckDB, no LFS file needed

_TRACKS = [
    {"artist": "Kassav'", "title": "Zouk-la sé sel médikaman nou ni"},
    {"artist": "Malavoi", "title": "La Filo", "mbid": "rec-123"},
]


def _analyzer() -> MagicMock:
    analyzer = MagicMock()
    analyzer.analyze.return_value = QueryAnalysis(
        original_query="",
        intent="recommendation",
        complexity="simple",
        expanded_query="",
        entities={},
        sub_queries=[],
        retrieval_mode="hybrid",
        confidence=0.95,
    )
    return analyzer


def _scripted_llm() -> AsyncMock:
    llm = AsyncMock()
    llm.ainvoke.side_effect = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "save_playlist",
                    "args": {"name": "Zouk Classics", "tracks": _TRACKS, "description": "d"},
                    "id": "tc-save",
                    "type": "tool_call",
                }
            ],
        ),
        AIMessage(content="Done — your playlist is handled."),
    ]
    return llm


_LIBRARY_SONG = {"id": "s1", "title": _TRACKS[0]["title"], "artist": "Kassav'", "album": "A"}


class _Navidrome:
    """search3 finds only the Kassav' song; createPlaylist is recorded."""

    def __init__(self) -> None:
        self.created: list[tuple[str, list[str]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.removeprefix("/rest/")
        q = request.url.params
        body: dict = {}
        if endpoint == "search3":
            hit = "zouk" in q["query"].lower()
            body = {"searchResult3": {"song": [_LIBRARY_SONG]} if hit else {}}
        elif endpoint == "createPlaylist":
            self.created.append((q["name"], q.get_list("songId")))
            body = {"playlist": {"id": "pl1", "name": q["name"], "songCount": 1, "entry": []}}
        return httpx.Response(200, json={"subsonic-response": {"status": "ok", **body}})


@pytest.fixture
def tmp_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, _Navidrome]:
    """Point the discover tools' DB + JSPF export at tmp_path, Navidrome at a fake."""
    import agent.tools.discover as discover
    import library.navidrome_playlist as navidrome_playlist

    db_path = tmp_path / "lw.duckdb"
    jspf_dir = tmp_path / "playlists"
    nd = _Navidrome()
    monkeypatch.setattr(
        discover,
        "get_connection",
        lambda read_only=False: duckdb.connect(str(db_path), read_only=read_only),
    )
    monkeypatch.setattr(discover, "JSPF_DIR", jspf_dir)
    monkeypatch.setattr(discover, "_schema_ready", False)
    monkeypatch.setattr(
        navidrome_playlist,
        "_client_from_settings",
        lambda: SubsonicClient("http://nd.test", "me", "pw", transport=httpx.MockTransport(nd)),
    )
    return db_path, jspf_dir, nd


async def _run_to_interrupt(graph, config: dict) -> dict:
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="save my zouk picks as a playlist")]}, config=config
    )
    [pending] = result["__interrupt__"]
    assert pending.value == {
        "type": "confirm_playlist_create",
        "name": "Zouk Classics",
        "track_count": 2,
        "description": "d",
    }
    return result


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 20}


@patch("agent.graph_nodes._query_analyzer", _analyzer())
async def test_approve_creates_navidrome_playlist_and_jspf(tmp_library) -> None:
    from agent.graph import build_graph

    db_path, jspf_dir, nd = tmp_library
    llm = _scripted_llm()
    with patch("agent.graph_nodes._llm_with_tools_instance", llm):
        graph = build_graph()
        config = _config("hitl-approve")
        await _run_to_interrupt(graph, config)
        assert not db_path.exists()  # nothing written before confirmation
        assert nd.created == []

        result = await graph.ainvoke(Command(resume=True), config=config)

    assert "__interrupt__" not in result
    assert llm.ainvoke.call_count == 2
    tool_msg = next(m for m in result["messages"] if getattr(m, "tool_call_id", "") == "tc-save")
    text = str(tool_msg.content)
    assert "Saved playlist 'Zouk Classics'" in text and "1 of 2 tracks matched" in text
    assert "- Malavoi — La Filo" in text  # reported as not in the library
    assert nd.created == [("Zouk Classics", ["s1"])]
    assert tool_msg.artifact == {
        "tracks": [{"artist": "Malavoi", "title": "La Filo", "mbid": "rec-123"}]
    }

    [jspf_path] = jspf_dir.glob("*.jspf")
    assert str(jspf_path) in text
    jspf = json.loads(jspf_path.read_text())
    assert jspf["playlist"]["title"] == "Zouk Classics"
    assert [t["creator"] for t in jspf["playlist"]["track"]] == ["Kassav'", "Malavoi"]
    assert jspf["playlist"]["track"][1]["identifier"] == [
        "https://musicbrainz.org/recording/rec-123"
    ]


@patch("agent.graph_nodes._query_analyzer", _analyzer())
async def test_reject_writes_nothing(tmp_library) -> None:
    from agent.graph import build_graph

    db_path, jspf_dir, nd = tmp_library
    llm = _scripted_llm()
    with patch("agent.graph_nodes._llm_with_tools_instance", llm):
        graph = build_graph()
        config = _config("hitl-reject")
        await _run_to_interrupt(graph, config)
        result = await graph.ainvoke(Command(resume=False), config=config)

    assert "__interrupt__" not in result
    tool_msg = next(m for m in result["messages"] if getattr(m, "tool_call_id", "") == "tc-save")
    assert "creation cancelled" in str(tool_msg.content)
    assert not db_path.exists()
    assert not jspf_dir.exists()
    assert nd.created == []
