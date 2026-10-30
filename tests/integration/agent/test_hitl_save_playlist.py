"""Scripted-LLM integration test for the save_playlist HITL interrupt → resume path.

The graph runs end to end with a fake tool-calling LLM; ``save_playlist`` hits
``interrupt()`` and is resumed with ``Command(resume=...)`` exactly as
``app/main.py`` does. DuckDB and the JSPF export dir are redirected to tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import duckdb
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from agent.intent import QueryAnalysis

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


@pytest.fixture
def tmp_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Point the discover tools' DB + JSPF export at tmp_path."""
    import agent.tools.discover as discover

    db_path = tmp_path / "lw.duckdb"
    jspf_dir = tmp_path / "playlists"
    monkeypatch.setattr(discover, "get_connection", lambda: duckdb.connect(str(db_path)))
    monkeypatch.setattr(discover, "JSPF_DIR", jspf_dir)
    monkeypatch.setattr(discover, "_schema_ready", False)
    return db_path, jspf_dir


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
async def test_approve_writes_playlist_row_and_jspf(tmp_library) -> None:
    from agent.graph import build_graph

    db_path, jspf_dir = tmp_library
    llm = _scripted_llm()
    with patch("agent.graph_nodes._llm_with_tools_instance", llm):
        graph = build_graph()
        config = _config("hitl-approve")
        await _run_to_interrupt(graph, config)
        assert not db_path.exists()  # nothing written before confirmation

        result = await graph.ainvoke(Command(resume=True), config=config)

    assert "__interrupt__" not in result
    assert llm.ainvoke.call_count == 2
    tool_msg = next(m for m in result["messages"] if getattr(m, "tool_call_id", "") == "tc-save")
    assert "Saved playlist 'Zouk Classics' with 2 tracks" in str(tool_msg.content)

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        [(pid, name)] = conn.execute("SELECT id, name FROM local_playlists").fetchall()
        tracks = conn.execute(
            "SELECT artist_name, track_name, mbid FROM local_playlist_tracks ORDER BY position"
        ).fetchall()
    finally:
        conn.close()
    assert name == "Zouk Classics"
    assert [(a, t) for a, t, _ in tracks] == [(x["artist"], x["title"]) for x in _TRACKS]

    jspf = json.loads((jspf_dir / f"{pid}.jspf").read_text())
    assert jspf["playlist"]["title"] == "Zouk Classics"
    assert [t["creator"] for t in jspf["playlist"]["track"]] == ["Kassav'", "Malavoi"]
    assert jspf["playlist"]["track"][1]["identifier"] == [
        "https://musicbrainz.org/recording/rec-123"
    ]


@patch("agent.graph_nodes._query_analyzer", _analyzer())
async def test_reject_writes_nothing(tmp_library) -> None:
    from agent.graph import build_graph

    db_path, jspf_dir = tmp_library
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
