"""MCP server parity with the agent tools — registration, artifact unwrap, direct save."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx
import pytest

from agent.tools import ALL_TOOLS
from mcp_server import server
from sources.schemas import TrackRef
from sources.subsonic import SubsonicClient


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
def isolated_save(tmp_path):
    """JSPF export → tmp_path, no match cache (the project DB is never opened)."""
    import agent.tools.discover as discover

    with (
        patch.object(discover, "JSPF_DIR", tmp_path),
        patch.object(discover, "match_cache", return_value=None),
    ):
        yield tmp_path


def test_save_playlist_skips_interrupt_and_saves_to_navidrome(isolated_save):
    import library.navidrome_playlist as navidrome_playlist

    created: list[list[str]] = []

    def nd(request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.removeprefix("/rest/")
        body: dict = {}
        if endpoint == "search3":
            song = {"id": "s1", "title": "x", "artist": "A"}
            body = {"searchResult3": {"song": [song]}}
        elif endpoint == "createPlaylist":
            created.append(request.url.params.get_list("songId"))
            body = {"playlist": {"id": "pl1", "name": "Mix", "entry": []}}
        return httpx.Response(200, json={"subsonic-response": {"status": "ok", **body}})

    client = SubsonicClient("http://nd.test", "me", "pw", transport=httpx.MockTransport(nd))
    with patch.object(navidrome_playlist, "_client_from_settings", return_value=client):
        out = asyncio.run(server.save_playlist("Mix", [TrackRef(artist="A", title="x")]))
    assert out.startswith("Saved playlist 'Mix' to the music library (Navidrome id pl1)")
    assert created == [["s1"]]
    assert len(list(isolated_save.glob("*.jspf"))) == 1


def test_save_playlist_without_navidrome_fails_cleanly(isolated_save):
    import library.navidrome_playlist as navidrome_playlist

    with patch.object(navidrome_playlist, "navidrome_configured", return_value=False):
        out = asyncio.run(server.save_playlist("Mix", [TrackRef(artist="A", title="x")]))
    assert "Navidrome isn't configured" in out
    assert len(list(isolated_save.glob("*.jspf"))) == 1  # the JSPF export still happens


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
