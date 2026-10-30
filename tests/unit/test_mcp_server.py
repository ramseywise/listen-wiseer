"""MCP server parity with the agent tools — registration, artifact unwrap, direct save."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from agent.tools import ALL_TOOLS
from mcp_server import server
from sources.schemas import TrackRef


def _tools() -> dict:
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


def test_exposes_agent_tools_except_memory():
    agent_names = {t.name for t in ALL_TOOLS} - {"manage_taste_memory", "search_taste_memory"}
    assert set(_tools()) == agent_names


def test_schema_comes_from_agent_signature():
    schema = _tools()["discover_tracks"].inputSchema
    assert schema["required"] == ["artist"]
    assert {"title", "n", "new_artist_ratio"} <= set(schema["properties"])


def test_content_and_artifact_tools_return_text_only():
    tracks = [TrackRef(artist="Radiohead", title="Creep")]
    with patch("agent.tools.music.lastfm.artist_top_tracks", return_value=tracks):
        result = asyncio.run(server.mcp.call_tool("get_artist_top_tracks", {"artist": "Radiohead"}))
    blocks = result[0] if isinstance(result, tuple) else result
    assert [b.text for b in blocks] == ["1. Radiohead — Creep"]


@pytest.fixture
def fake_db(mem_conn):
    @contextmanager
    def _db():
        yield mem_conn

    with patch.object(server, "db", _db):
        yield mem_conn


def test_save_playlist_skips_interrupt(fake_db, tmp_path):
    with patch.object(server, "JSPF_DIR", tmp_path):
        out = server.save_playlist("Mix", [TrackRef(artist="A", title="x")])
    assert out.startswith("Saved playlist 'Mix' with 1 tracks")
    assert len(list(tmp_path.glob("*.jspf"))) == 1
    assert fake_db.execute("SELECT count(*) FROM local_playlist_tracks").fetchone() == (1,)


def test_http_bind_follows_settings():
    from utils.config import settings

    assert server.mcp.settings.host == settings.mcp_server_host
    assert server.mcp.settings.port == settings.mcp_server_port


def test_transport_defaults_to_stdio_and_rejects_unknown(monkeypatch):
    from pydantic import ValidationError

    from utils.config import Settings

    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    assert Settings(_env_file=None).mcp_transport == "stdio"
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    assert Settings(_env_file=None).mcp_transport == "streamable-http"
    monkeypatch.setenv("MCP_TRANSPORT", "sse")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
