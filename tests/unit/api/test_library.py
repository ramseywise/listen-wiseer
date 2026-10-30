"""Unit tests for api.library — every route against a fake Navidrome."""

import httpx
import pytest

from api.library import _relay
from tests.unit.api.conftest import AUDIO, COVER, failed, refused


class TestHealth:
    def test_up(self, api):
        assert api.get("/api/health").json() == {"navidrome": True, "songCount": 3}

    def test_down_is_still_200(self, make_api):
        response = make_api(refused).get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"navidrome": False, "songCount": 0}


class TestBrowse:
    def test_artists(self, api):
        assert api.get("/api/artists").json() == [
            {"id": "ar1", "name": "ProleteR", "albumCount": 2, "coverArt": "ar-ar1"}
        ]

    def test_artist_with_albums_camel_case(self, api):
        body = api.get("/api/artists/ar1").json()
        assert body["name"] == "ProleteR"
        assert [a["id"] for a in body["albums"]] == ["al1", "al2"]
        assert body["albums"][0] == {
            "id": "al1", "name": "Album al1", "artist": "ProleteR", "artistId": "ar1",
            "year": 2011, "songCount": 2, "duration": 400, "coverArt": "al-al1",
        }  # fmt: skip

    def test_artist_songs_in_album_order(self, api):
        body = api.get("/api/artists/ar1/songs").json()
        assert [s["id"] for s in body] == ["s1", "s2", "s3"]

    def test_album_with_songs(self, api):
        body = api.get("/api/albums/al1").json()
        assert body["songCount"] == 2
        assert body["songs"][0] == {
            "id": "s1",
            "title": "April Showers",
            "artist": "ProleteR",
            "artistId": "ar1",
            "album": "Album al1",
            "albumId": "al1",
            "track": 1,
            "year": 2011,
            "duration": 200,
            "coverArt": "mf-s1",
            "suffix": "mp3",
            "starred": False,
        }  # fmt: skip  — empty mbid omitted, not null

    def test_album_list_paging_and_total(self, api):
        response = api.get("/api/albums", params={"type": "newest", "size": 1, "offset": 1})
        assert [a["id"] for a in response.json()] == ["al2"]
        assert response.headers["x-total-count"] == "2"

    @pytest.mark.parametrize("list_type", ["recent", "frequent", "random", "alphabeticalByName"])
    def test_album_list_types(self, api, list_type):
        assert api.get("/api/albums", params={"type": list_type}).status_code == 200

    def test_album_list_rejects_unknown_type(self, api):
        assert api.get("/api/albums", params={"type": "starred"}).status_code == 422


class TestSearch:
    def test_songs_found(self, api):
        body = api.get("/api/search", params={"q": "soul", "limit": 5}).json()
        assert body["artists"] == [] and body["albums"] == []
        assert [s["id"] for s in body["songs"]] == ["s3"]

    def test_blank_query_is_empty_not_everything(self, api):
        assert api.get("/api/search", params={"q": "  "}).json() == {
            "artists": [],
            "albums": [],
            "songs": [],
        }


class TestErrors:
    @pytest.mark.parametrize(
        "path", ["/api/artists/nope", "/api/albums/nope", "/api/artists/nope/songs"]
    )
    def test_missing_item_404(self, api, path):
        response = api.get(path)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @pytest.mark.parametrize(
        "path", ["/api/artists", "/api/albums/al1", "/api/search?q=x", "/api/stream/s1"]
    )
    def test_navidrome_down_503(self, make_api, path):
        response = make_api(refused).get(path)
        assert response.status_code == 503
        assert response.json() == {"detail": "Navidrome is unavailable"}

    def test_bad_credentials_503(self, make_api):
        response = make_api(lambda _r: failed(40, "Wrong username or password")).get("/api/artists")
        assert response.status_code == 503

    def test_other_subsonic_error_502(self, make_api):
        response = make_api(lambda _r: failed(0, "boom")).get("/api/artists")
        assert response.status_code == 502
        assert "boom" in response.json()["detail"]


class TestCover:
    def test_bytes_and_cache_headers(self, api):
        response = api.get("/api/cover/al-al1", params={"size": 300})
        assert response.status_code == 200
        assert response.content == COVER
        assert response.headers["content-type"] == "image/jpeg"
        assert "max-age" in response.headers["cache-control"]

    def test_missing_cover_404(self, api):
        assert api.get("/api/cover/nope").status_code == 404


class TestStream:
    def test_full_body_without_range(self, api):
        response = api.get("/api/stream/s1")
        assert response.status_code == 200
        assert response.content == AUDIO
        assert response.headers["accept-ranges"] == "bytes"
        assert "set-cookie" not in response.headers  # Navidrome's cookies stay upstream

    def test_range_returns_206_and_exact_slice(self, api):
        response = api.get("/api/stream/s1", headers={"Range": "bytes=1000-2023"})
        assert response.status_code == 206
        assert response.content == AUDIO[1000:2024]
        assert response.headers["content-range"] == f"bytes 1000-2023/{len(AUDIO)}"
        assert response.headers["content-length"] == "1024"
        assert response.headers["content-type"] == "audio/mpeg"

    def test_open_ended_range(self, api):
        response = api.get("/api/stream/s1", headers={"Range": "bytes=10000-"})
        assert response.status_code == 206
        assert response.content == AUDIO[10000:]

    def test_unknown_song_404(self, api):
        assert api.get("/api/stream/nope").status_code == 404


async def test_relay_closes_upstream_when_client_leaves():
    upstream = httpx.Response(200, stream=httpx.ByteStream(b"x" * 10))
    body = _relay(upstream)
    await body.__anext__()
    await body.aclose()  # what Starlette does when the browser disconnects mid-stream
    assert upstream.is_closed
