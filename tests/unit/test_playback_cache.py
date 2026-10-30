"""Unit tests for library.playback cache paths not covered in test_library.py."""

from __future__ import annotations

from datetime import datetime

import duckdb
import httpx

from etl.history import track_key
from library.playback import playable
from sources import youtube
from sources.http import SourceClient


def _client(handler) -> SourceClient:
    return SourceClient("test", "https://api.test/", transport=httpx.MockTransport(handler))


def _no_deezer(_r: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"data": []})


class _YouTube:
    def __init__(self, video_id: str) -> None:
        self.calls = 0
        self.video_id = video_id

    def __call__(self, _r: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(200, json={"items": [{"id": {"videoId": self.video_id}}]})


def test_without_conn_resolves_live_and_never_caches() -> None:
    yt = _YouTube("live1")
    track = playable("A", "One", deezer_client=_client(_no_deezer), youtube_client=_client(yt))
    assert track.youtube_embed_url == "https://www.youtube.com/embed/live1"
    assert track.local_path == ""
    assert yt.calls == 1


def test_preseeded_cache_hit_skips_search(mem_conn: duckdb.DuckDBPyConnection) -> None:
    mem_conn.execute(
        "INSERT INTO playable_cache VALUES (?, ?, ?)",
        [track_key("A", "One"), "cached1", datetime(2026, 1, 1)],
    )
    yt = _YouTube("fresh")
    track = playable(
        "A", "One", conn=mem_conn, deezer_client=_client(_no_deezer), youtube_client=_client(yt)
    )
    assert track.youtube_url == "https://www.youtube.com/watch?v=cached1"
    assert yt.calls == 0


def test_cache_miss_without_youtube_key_falls_back_to_search_link(
    mem_conn: duckdb.DuckDBPyConnection, monkeypatch
) -> None:
    monkeypatch.setattr(youtube, "default_client", lambda: None)
    track = playable("A", "One", conn=mem_conn, deezer_client=_client(_no_deezer))
    assert track.youtube_url.startswith("https://www.youtube.com/results?")
    assert mem_conn.execute("SELECT COUNT(*) FROM playable_cache").fetchone() == (0,)
