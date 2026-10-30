"""Unit tests for sources.subsonic — async client over httpx.MockTransport, no network."""

import hashlib
from collections.abc import Callable

import httpx
import pytest

from sources.subsonic import (
    API_VERSION,
    CLIENT_NAME,
    Song,
    SubsonicClient,
    SubsonicError,
    SubsonicNotFound,
    SubsonicUnavailable,
    token_params,
    unwrap,
)

Handler = Callable[[httpx.Request], httpx.Response]


def _ok(**body) -> dict:
    return {"subsonic-response": {"status": "ok", "version": API_VERSION, **body}}


def _failed(code: int, message: str) -> dict:
    return {"subsonic-response": {"status": "failed", "error": {"code": code, "message": message}}}


def _client(handler: Handler) -> SubsonicClient:
    return SubsonicClient("http://nd.test/", "me", "pw", transport=httpx.MockTransport(handler))


def _json(payload: dict, seen: list[httpx.Request] | None = None) -> SubsonicClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=payload)

    return _client(handler)


_SONG = {
    "id": "s1",
    "title": "April Showers",
    "artist": "ProleteR",
    "artistId": "ar1",
    "album": "Curses",
    "albumId": "al1",
    "track": 1,
    "year": 2011,
    "duration": 215,
    "coverArt": "mf-s1",
    "musicBrainzId": "",
    "suffix": "mp3",
    "starred": "2026-10-30T10:00:00Z",
    "path": "ProleteR/Curses/01.mp3",
}


class TestAuth:
    def test_token_is_md5_of_password_plus_salt(self):
        params = token_params("me", "pw", salt="abc")
        assert params["t"] == hashlib.md5(b"pwabc").hexdigest()  # noqa: S324
        assert (params["u"], params["s"], params["f"]) == ("me", "abc", "json")
        assert (params["v"], params["c"]) == (API_VERSION, CLIENT_NAME)

    def test_fresh_salt_per_call(self):
        assert token_params("me", "pw")["s"] != token_params("me", "pw")["s"]

    async def test_every_request_carries_auth_not_password(self):
        seen: list[httpx.Request] = []
        await _json(_ok(), seen).ping()
        q = seen[0].url.params
        assert seen[0].url.path == "/rest/ping"
        assert {"u", "t", "s", "v", "c", "f"} <= set(q.keys())
        assert "pw" not in str(seen[0].url)


class TestEnvelope:
    def test_ok_returns_body(self):
        assert unwrap(_ok(song=_SONG))["song"]["id"] == "s1"

    def test_not_found_code(self):
        with pytest.raises(SubsonicNotFound):
            unwrap(_failed(70, "Album not found"))

    def test_auth_failure_is_unavailable(self):
        with pytest.raises(SubsonicUnavailable, match="credentials"):
            unwrap(_failed(40, "Wrong username or password"))

    def test_other_error_code(self):
        with pytest.raises(SubsonicError) as exc:
            unwrap(_failed(10, "missing id"))
        assert exc.value.code == 10 and not isinstance(exc.value, SubsonicNotFound)

    def test_not_an_envelope(self):
        with pytest.raises(SubsonicError):
            unwrap({"hello": "world"})

    async def test_connection_error_is_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        with pytest.raises(SubsonicUnavailable):
            await _client(handler).ping()

    async def test_http_5xx_is_unavailable(self):
        with pytest.raises(SubsonicUnavailable):
            await _client(lambda _r: httpx.Response(502)).ping()


class TestModels:
    def test_song_maps_subsonic_fields(self):
        song = Song.model_validate(_SONG)
        assert song.mbid is None  # "" → None
        assert song.starred is True
        dumped = song.model_dump(by_alias=True, exclude_none=True)
        assert dumped["artistId"] == "ar1" and dumped["coverArt"] == "mf-s1"
        assert "mbid" not in dumped and "path" not in dumped

    def test_unstarred_and_mbid(self):
        song = Song.model_validate({**_SONG, "starred": None, "musicBrainzId": "rec-1"})
        assert (song.starred, song.mbid) == (False, "rec-1")


class TestCalls:
    async def test_artists_flattens_index(self):
        payload = _ok(
            artists={
                "index": [
                    {"name": "M", "artist": [{"id": "a1", "name": "Miranda", "albumCount": 1}]},
                    {"name": "P", "artist": [{"id": "a2", "name": "ProleteR", "albumCount": 2}]},
                ]
            }
        )
        found = await _json(payload).artists()
        assert [(a.id, a.album_count) for a in found] == [("a1", 1), ("a2", 2)]

    async def test_artist_with_albums(self):
        payload = _ok(
            artist={
                "id": "a2",
                "name": "ProleteR",
                "albumCount": 1,
                "album": [{"id": "al1", "name": "Curses", "songCount": 3, "duration": 600}],
            }  # fmt: skip
        )
        artist = await _json(payload).artist("a2")
        assert artist.albums[0].song_count == 3

    async def test_album_with_songs(self):
        payload = _ok(album={"id": "al1", "name": "Curses", "song": [_SONG]})
        album = await _json(payload).album("al1")
        assert [s.id for s in album.songs] == ["s1"]

    async def test_album_list_reads_total_header(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            body = _ok(albumList2={"album": [{"id": "al1", "name": "Curses"}]})
            return httpx.Response(200, json=body, headers={"x-total-count": "7"})

        page = await _client(handler).album_list("newest", size=5, offset=10)
        assert page.total == 7 and page.albums[0].id == "al1"
        q = seen[0].url.params
        assert (q["type"], q["size"], q["offset"]) == ("newest", "5", "10")

    async def test_album_list_empty_without_header(self):
        page = await _json(_ok(albumList2={})).album_list("recent")
        assert page.albums == [] and page.total is None

    async def test_search_missing_keys_are_empty(self):
        res = await _json(_ok(searchResult3={"song": [_SONG]})).search("april")
        assert (res.artists, res.albums, [s.id for s in res.songs]) == ([], [], ["s1"])

    async def test_scan_status(self):
        status = await _json(_ok(scanStatus={"scanning": False, "count": 5})).scan_status()
        assert status.count == 5

    async def test_start_scan_full_flag(self):
        seen: list[httpx.Request] = []
        await _json(_ok(scanStatus={"scanning": True}), seen).start_scan(full=True)
        assert seen[0].url.params["fullScan"] == "true"

    async def test_missing_album_raises_not_found(self):
        with pytest.raises(SubsonicNotFound):
            await _json(_failed(70, "Album not found")).album("nope")


class TestBinary:
    async def test_stream_forwards_range_and_requests_raw(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(206, content=b"abc", headers={"content-type": "audio/mpeg"})

        response = await _client(handler).open_stream("s1", range_header="bytes=0-2")
        try:
            assert response.status_code == 206
            assert (await response.aread()) == b"abc"
        finally:
            await response.aclose()
        assert seen[0].headers["range"] == "bytes=0-2"
        assert seen[0].url.params["format"] == "raw"

    async def test_stream_error_envelope_raises(self):
        with pytest.raises(SubsonicNotFound):
            await _json(_failed(70, "data not found")).open_stream("nope")

    async def test_cover_art_bytes(self):
        client = _client(
            lambda _r: httpx.Response(
                200, content=b"\xff\xd8", headers={"content-type": "image/jpeg"}
            )
        )
        assert (await client.cover_art("al-1", size=300)).content == b"\xff\xd8"

    async def test_cover_art_error_envelope_raises(self):
        with pytest.raises(SubsonicNotFound):
            await _json(_failed(70, "Artwork not found")).cover_art("nope")


def test_song_title_whitespace_stripped() -> None:
    assert Song.model_validate({"id": "1", "title": " Rainy thoughts \n"}).title == "Rainy thoughts"
