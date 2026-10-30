"""Fixtures for api/ tests — the FastAPI app over a fake Navidrome (httpx.MockTransport)."""

import re
from collections.abc import Callable, Iterator
from pathlib import Path

import duckdb
import httpx
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import DbConnect
from etl.db import init_schema
from sources.subsonic import SubsonicClient

AUDIO = bytes(range(256)) * 40  # 10 240 bytes; distinct values make slices checkable
COVER = b"\xff\xd8\xff\xe0fake-jpeg"


def _song(sid: str, title: str, album_id: str, track: int) -> dict:
    return {
        "id": sid, "title": title, "artist": "ProleteR", "artistId": "ar1",
        "album": f"Album {album_id}", "albumId": album_id, "track": track, "year": 2011,
        "duration": 200, "coverArt": f"mf-{sid}", "musicBrainzId": "", "suffix": "mp3",
    }  # fmt: skip


SONGS = {
    "al1": [_song("s1", "April Showers", "al1", 1), _song("s2", "Downtown Irony", "al1", 2)],
    "al2": [_song("s3", "Soul Key", "al2", 1)],
}
ALBUMS = {
    aid: {
        "id": aid,
        "name": f"Album {aid}",
        "artist": "ProleteR",
        "artistId": "ar1",
        "year": 2011,
        "songCount": len(songs),
        "duration": 200 * len(songs),
        "coverArt": f"al-{aid}",
    }  # fmt: skip
    for aid, songs in SONGS.items()
}
ARTIST = {"id": "ar1", "name": "ProleteR", "albumCount": 2, "coverArt": "ar-ar1"}


def ok(**body) -> httpx.Response:
    return httpx.Response(200, json={"subsonic-response": {"status": "ok", **body}})


def failed(code: int, message: str) -> httpx.Response:
    envelope = {"status": "failed", "error": {"code": code, "message": message}}
    return httpx.Response(200, json={"subsonic-response": envelope})


def _stream(request: httpx.Request) -> httpx.Response:
    """Serve AUDIO honouring a single ``bytes=a-b`` / ``bytes=a-`` range, like Navidrome.

    ``stream=`` (not ``content=``) so the body arrives unread, as from a real socket.
    """
    headers = {"content-type": "audio/mpeg", "accept-ranges": "bytes", "set-cookie": "nd=1"}
    m = re.fullmatch(r"bytes=(\d+)-(\d*)", request.headers.get("range", ""))
    status, body = 200, AUDIO
    if m:
        start = int(m[1])
        end = int(m[2]) if m[2] else len(AUDIO) - 1
        status, body = 206, AUDIO[start : end + 1]
        headers["content-range"] = f"bytes {start}-{end}/{len(AUDIO)}"
    headers["content-length"] = str(len(body))
    return httpx.Response(status, stream=httpx.ByteStream(body), headers=headers)


def navidrome(request: httpx.Request) -> httpx.Response:
    """Just enough Subsonic for the library routes; unknown ids → code 70."""
    endpoint = request.url.path.removeprefix("/rest/")
    q = request.url.params
    item = q.get("id", "")
    if endpoint == "getScanStatus":
        return ok(scanStatus={"scanning": False, "count": 3, "folderCount": 2})
    if endpoint == "getArtists":
        return ok(artists={"index": [{"name": "P", "artist": [ARTIST]}]})
    if endpoint == "getArtist":
        if item != "ar1":
            return failed(70, "Artist not found")
        return ok(artist={**ARTIST, "album": list(ALBUMS.values())})
    if endpoint == "getAlbum":
        if item not in ALBUMS:
            return failed(70, "Album not found")
        return ok(album={**ALBUMS[item], "song": SONGS[item]})
    if endpoint == "getAlbumList2":
        start, size = int(q.get("offset", 0)), int(q.get("size", 10))
        page = list(ALBUMS.values())[start : start + size]
        response = ok(albumList2={"album": page})
        response.headers["x-total-count"] = str(len(ALBUMS))
        return response
    if endpoint == "search3":
        hits = [
            s for songs in SONGS.values() for s in songs if q["query"].lower() in s["title"].lower()
        ]
        return ok(searchResult3={"song": hits[: int(q["songCount"])]} if hits else {})
    if endpoint == "getCoverArt":
        if not item.startswith(("al-", "mf-", "ar-")):
            return failed(70, "Artwork not found")
        return httpx.Response(
            200,
            content=COVER,
            headers={"content-type": "image/jpeg", "cache-control": "public, max-age=31536000"},
        )
    if endpoint == "stream":
        if item not in {s["id"] for songs in SONGS.values() for s in songs}:
            return failed(70, "data not found")
        return _stream(request)
    return failed(0, f"unhandled endpoint {endpoint}")


def refused(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def connect_to(path: Path) -> DbConnect:
    """``get_connection`` stand-in over a tmp file — tests never open the project DB."""

    def _connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(path), read_only=read_only)

    return _connect


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Empty project schema in a tmp DuckDB file."""
    path = tmp_path / "api.db"
    conn = duckdb.connect(str(path))
    init_schema(conn)
    conn.close()
    return path


@pytest.fixture
def make_api(tmp_path: Path) -> Iterator[Callable[..., TestClient]]:
    """TestClient over a fake Navidrome; pass another handler to simulate failures.
    ``db_connect`` defaults to a fresh tmp file (no schema)."""
    opened: list[TestClient] = []

    def _make(
        handler: Callable[[httpx.Request], httpx.Response] = navidrome,
        db_connect: DbConnect | None = None,
    ) -> TestClient:
        subsonic = SubsonicClient(
            "http://nd.test", "me", "pw", transport=httpx.MockTransport(handler)
        )
        db_connect = db_connect or connect_to(tmp_path / "default.db")
        client = TestClient(create_app(subsonic=subsonic, db_connect=db_connect))
        client.__enter__()
        opened.append(client)
        return client

    yield _make
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def api(make_api) -> TestClient:
    return make_api()


# ── Stateful Navidrome (playlists, stars, scrobbles, play queue) ─────────────


class FakeNavidrome:
    """``navidrome`` plus the write endpoints, with state; records scrobbles."""

    def __init__(self) -> None:
        self.songs = {s["id"]: s for songs in SONGS.values() for s in songs}
        self.playlists: dict[str, dict] = {}
        self.starred: list[str] = []
        self.scrobbles: list[dict[str, str]] = []
        self.queue: dict | None = None
        self._next = 0

    def _playlist(self, pid: str, *, entries: bool) -> dict:
        p = self.playlists[pid]
        songs = [self.songs[i] for i in p["ids"]]
        out = {
            "id": pid, "name": p["name"], "songCount": len(songs),
            "duration": sum(s["duration"] for s in songs), "coverArt": f"pl-{pid}",
            "changed": "2026-10-30T12:00:00Z", "owner": "me",
        }  # fmt: skip
        return {**out, "entry": songs} if entries else out

    def __call__(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.removeprefix("/rest/")
        q = request.url.params
        if endpoint == "getSong":
            song = self.songs.get(q.get("id", ""))
            return ok(song=song) if song else failed(70, "Song not found")
        if endpoint == "getPlaylists":
            return ok(
                playlists={"playlist": [self._playlist(p, entries=False) for p in self.playlists]}
            )
        if endpoint in {"getPlaylist", "deletePlaylist"}:
            pid = q.get("id", "")
            if pid not in self.playlists:
                return failed(70, "Playlist not found")
            if endpoint == "deletePlaylist":
                del self.playlists[pid]
                return ok()
            return ok(playlist=self._playlist(pid, entries=True))
        if endpoint == "createPlaylist":
            ids = q.get_list("songId")
            if unknown := [i for i in ids if i not in self.songs]:
                return failed(70, f"song {unknown[0]} not found")
            pid = q.get("playlistId")
            if pid:  # replace the songs, keep the name (Navidrome semantics)
                if pid not in self.playlists:
                    return failed(70, "Playlist not found")
                if ids:
                    self.playlists[pid]["ids"] = ids
            else:
                self._next += 1
                pid = f"pl{self._next}"
                self.playlists[pid] = {"name": q["name"], "ids": ids}
            return ok(playlist=self._playlist(pid, entries=True))
        if endpoint == "updatePlaylist":
            pid = q.get("playlistId", "")
            if pid not in self.playlists:
                return failed(70, "Playlist not found")
            p = self.playlists[pid]
            drop = {int(i) for i in q.get_list("songIndexToRemove")}
            p["ids"] = [s for n, s in enumerate(p["ids"]) if n not in drop]
            p["ids"] += q.get_list("songIdToAdd")
            if "name" in q:
                p["name"] = q["name"]
            return ok()
        if endpoint in {"star", "unstar"}:
            sid = q.get("id", "")
            if sid not in self.songs:
                return failed(70, "Song not found")
            if endpoint == "star" and sid not in self.starred:
                self.starred.append(sid)
            if endpoint == "unstar" and sid in self.starred:
                self.starred.remove(sid)
            return ok()
        if endpoint == "getStarred2":
            songs = [{**self.songs[i], "starred": "2026-10-30T12:00:00Z"} for i in self.starred]
            return ok(starred2={"song": songs} if songs else {})
        if endpoint == "scrobble":
            self.scrobbles.append({k: v for k, v in q.items() if k in {"id", "submission", "time"}})
            return ok()
        if endpoint == "savePlayQueue":
            ids = q.get_list("id")
            self.queue = (
                {"entry": [self.songs[i] for i in ids], "current": q.get("current"),
                 "position": int(q.get("position", 0))}
                if ids else None
            )  # fmt: skip
            return ok()
        if endpoint == "getPlayQueue":
            return ok(playQueue=self.queue or {"username": "me", "changedBy": ""})
        return navidrome(request)


@pytest.fixture
def fake_nd() -> FakeNavidrome:
    return FakeNavidrome()


@pytest.fixture
def nd_api(make_api, fake_nd: FakeNavidrome, db_path: Path) -> TestClient:
    """Stateful fake Navidrome + a tmp DuckDB with the project schema."""
    return make_api(fake_nd, db_connect=connect_to(db_path))
