"""DuckDB single-writer rule: the MCP server reads read-only; the API process is the writer."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import duckdb
import httpx
import pytest

from agent.tools import discover as tools
from agent.tools import downloads
from etl.db import init_schema
from library.playback import playable
from sources.http import SourceClient
from sources.schemas import FreeTrack


@pytest.fixture
def db_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tmp DuckDB with the project schema; ``get_connection`` in the tools points at it."""
    path = tmp_path / "lw.db"
    conn = duckdb.connect(str(path))
    init_schema(conn)
    conn.execute("INSERT INTO playable_cache VALUES ('a\tx', 'vid1', now())")
    conn.close()

    def _connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(path), read_only=read_only)

    monkeypatch.setattr(tools, "get_connection", _connect)
    monkeypatch.setattr(tools, "_schema_ready", False)
    return path


@pytest.fixture
def read_only_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "_read_only", False)
    tools.use_read_only_db()  # restored to False by monkeypatch on teardown


@contextmanager
def _writer_process(path: Path) -> Iterator[None]:
    """Another process (the API) holding the DuckDB write lock."""
    code = (
        "import duckdb, sys; c = duckdb.connect(sys.argv[1]); "
        "print('ready', flush=True); sys.stdin.read()"
    )
    proc = subprocess.Popen(  # noqa: S603 — fixed argv, sys.executable
        [sys.executable, "-c", code, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "ready"
        yield
    finally:
        proc.communicate(timeout=10)


def test_default_db_is_read_write(db_file: Path) -> None:
    with tools.db() as conn:
        conn.execute("INSERT INTO playable_cache VALUES ('b\ty', 'vid2', now())")


def test_read_only_mode_reads_but_cannot_write(db_file: Path, read_only_mode: None) -> None:
    with tools.db() as conn:
        assert conn.execute("SELECT count(*) FROM playable_cache").fetchall() == [(1,)]
        with pytest.raises(duckdb.InvalidInputException):
            conn.execute("DELETE FROM playable_cache")


def test_explicit_write_still_opens_read_write(db_file: Path, read_only_mode: None) -> None:
    with tools.db(write=True) as conn:
        conn.execute("DELETE FROM playable_cache")


def test_read_only_match_cache_reads_and_skips_writes(db_file: Path, read_only_mode: None) -> None:
    conn = duckdb.connect(str(db_file))
    conn.execute("INSERT INTO track_xref (track_key, navidrome_id) VALUES ('a\tx', 's1')")
    conn.close()
    cache = tools.match_cache()
    assert cache.read_only
    cache.put_many([("b\ty", "B", "y", "s2", 0.9)])
    cache.forget(["a\tx"])
    assert cache.get_many(["a\tx", "b\ty"]) == {"a\tx": ("s1", 0.0)}


def test_playable_skips_cache_write_on_read_only_conn(db_file: Path) -> None:
    def _client(body: dict) -> SourceClient:
        transport = httpx.MockTransport(lambda _r: httpx.Response(200, json=body))
        return SourceClient("test", "https://api.test/", transport=transport)

    conn = duckdb.connect(str(db_file), read_only=True)
    p = playable("New", "Song", conn=conn, deezer_client=_client({"data": []}),
                 youtube_client=_client({"items": [{"id": {"videoId": "vid9"}}]}))  # fmt: skip
    conn.close()
    assert p.youtube_embed_url.endswith("/vid9")


def test_download_reports_locked_db_clearly(db_file: Path, read_only_mode: None) -> None:
    track = FreeTrack(source="jamendo", source_id="1", artist="A", title="x",
                      download_url="https://dl.test/x.mp3", license_url="https://cc/by")  # fmt: skip
    with (
        _writer_process(db_file),
        patch.object(downloads, "find_free", return_value=[track]),
        patch.object(downloads, "download") as dl,
    ):
        out = downloads._download_track("A", "x", mbid="m")
    dl.assert_not_called()
    assert "in use by another process" in out


def test_mcp_main_switches_to_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_server import server

    monkeypatch.setattr(tools, "_read_only", False)
    with patch.object(server.mcp, "run") as run:
        server.main()
    run.assert_called_once()
    assert tools._read_only is True
