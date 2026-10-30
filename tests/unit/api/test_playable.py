"""``/api/playable`` — library match first, else Deezer preview / YouTube fallback."""

from collections.abc import Callable

import duckdb
from fastapi.testclient import TestClient

from api.playable import get_fallback, get_match_cache
from library.match import DuckDBMatchCache
from sources.schemas import PlayableTrack
from tests.unit.api.conftest import connect_to, refused


def _fallback(calls: list[tuple[str, str]]) -> Callable[[str, str], PlayableTrack]:
    def fallback(artist: str, title: str) -> PlayableTrack:
        calls.append((artist, title))
        return PlayableTrack(
            artist=artist,
            title=title,
            youtube_url="https://www.youtube.com/watch?v=abc",
            preview_url="https://cdn.deezer.test/p.mp3",
        )

    return fallback


def _wire(api: TestClient, calls: list[tuple[str, str]], cache=None) -> TestClient:
    app = api.app
    app.dependency_overrides[get_fallback] = lambda: _fallback(calls)  # type: ignore[attr-defined]
    app.dependency_overrides[get_match_cache] = lambda: cache  # type: ignore[attr-defined]
    return api


def test_library_track_gets_song_id_and_cover(api: TestClient) -> None:
    calls: list[tuple[str, str]] = []
    r = _wire(api, calls).get(
        "/api/playable", params={"artist": "ProleteR", "title": "April Showers"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["songId"] == "s1"
    assert body["coverUrl"] == "/api/cover/mf-s1?size=300"
    assert body["song"]["id"] == "s1"
    assert "previewUrl" not in body and "youtubeUrl" not in body
    assert calls == []  # no preview lookup for library tracks


def test_non_library_track_falls_back_to_preview_and_youtube(api: TestClient) -> None:
    calls: list[tuple[str, str]] = []
    r = _wire(api, calls).get("/api/playable", params={"artist": "Radiohead", "title": "Reckoner"})
    assert r.json() == {
        "artist": "Radiohead",
        "title": "Reckoner",
        "previewUrl": "https://cdn.deezer.test/p.mp3",
        "youtubeUrl": "https://www.youtube.com/watch?v=abc",
    }
    assert calls == [("Radiohead", "Reckoner")]


def test_navidrome_down_still_falls_back(make_api) -> None:
    calls: list[tuple[str, str]] = []
    api = _wire(make_api(refused), calls)
    r = api.get("/api/playable", params={"artist": "ProleteR", "title": "April Showers"})
    assert r.status_code == 200
    assert r.json()["previewUrl"] == "https://cdn.deezer.test/p.mp3"


def test_fallback_failure_returns_bare_identity(api: TestClient) -> None:
    def broken(artist: str, title: str) -> PlayableTrack:
        raise duckdb.IOException("locked")

    api.app.dependency_overrides[get_fallback] = lambda: broken  # type: ignore[attr-defined]
    api.app.dependency_overrides[get_match_cache] = lambda: None  # type: ignore[attr-defined]
    r = api.get("/api/playable", params={"artist": "X", "title": "Y"})
    assert r.json() == {"artist": "X", "title": "Y"}


def test_match_is_cached_in_track_xref(api: TestClient, db_path) -> None:
    calls: list[tuple[str, str]] = []
    cache = DuckDBMatchCache(connect_to(db_path))
    _wire(api, calls, cache).get(
        "/api/playable", params={"artist": "ProleteR", "title": "April Showers"}
    )
    with duckdb.connect(str(db_path), read_only=True) as conn:
        rows = conn.execute("SELECT navidrome_id FROM track_xref").fetchall()
    assert rows == [("s1",)]


def test_artist_and_title_are_required(api: TestClient) -> None:
    assert api.get("/api/playable", params={"artist": "X"}).status_code == 422
