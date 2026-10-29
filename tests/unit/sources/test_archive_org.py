"""Unit tests for sources.archive_org."""

import httpx

from sources import archive_org

_SEARCH = {"response": {"docs": [{"identifier": "show1"}]}}


def _file(name: str, fmt: str, title: str, creator: str = "") -> dict:
    return {"name": name, "format": fmt, "title": title, "creator": creator}


def _metadata(files: list[dict], **meta) -> dict:
    return {"metadata": {"identifier": "show1", "creator": "Band A", **meta}, "files": files}


def _client(make_client, metadata: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("advancedsearch.php"):
            return httpx.Response(200, json=_SEARCH)
        return httpx.Response(200, json=metadata)

    return make_client(handler)


class TestSearchItems:
    def test_query_and_identifiers(self, json_client):
        client, seen = json_client(_SEARCH)
        assert archive_org.search_items('Band "A"', "Song", client=client) == ["show1"]
        q = seen[0].url.params["q"]
        assert q == 'creator:("Band A") AND mediatype:audio AND "Song"'


class TestItemTracks:
    def test_prefers_vbr_mp3_and_builds_urls(self, json_client):
        files = [
            _file("t01.mp3", "VBR MP3", "Ripple"),
            _file("t01_64kb.mp3", "64Kbps MP3", "Ripple"),
            _file("t01.flac", "Flac", "Ripple"),
            _file("my song.mp3", "VBR MP3", ""),
        ]
        client, _ = json_client(_metadata(files, licenseurl="https://cc/by/4.0"))
        tracks = archive_org.item_tracks("show1", client=client)
        assert [t.title for t in tracks] == ["Ripple", "my song"]
        assert tracks[0].artist == "Band A"
        assert tracks[0].license_url == "https://cc/by/4.0"
        assert tracks[1].download_url == "https://archive.org/download/show1/my%20song.mp3"

    def test_restricted_item_skipped(self, json_client):
        client, _ = json_client(
            _metadata([_file("a.mp3", "VBR MP3", "x")], **{"access-restricted-item": "true"})
        )
        assert archive_org.item_tracks("show1", client=client) == []

    def test_missing_item(self, json_client):
        client, _ = json_client({})
        assert archive_org.item_tracks("nope", client=client) == []


class TestFindTracks:
    def test_filters_by_title_and_file_creator(self, make_client):
        files = [
            _file("a.mp3", "VBR MP3", "Ripple"),
            _file("b.mp3", "VBR MP3", "Ripple", creator="Tribute Band"),
            _file("c.mp3", "VBR MP3", "Loser"),
        ]
        client = _client(make_client, _metadata(files))
        tracks = archive_org.find_tracks("band a", "ripple", client=client)
        assert [(t.artist, t.title) for t in tracks] == [("Band A", "Ripple")]

    def test_no_title_returns_all_up_to_limit(self, make_client):
        files = [_file(f"{i}.mp3", "VBR MP3", f"Song {i}") for i in range(5)]
        client = _client(make_client, _metadata(files))
        assert len(archive_org.find_tracks("Band A", limit=3, client=client)) == 3
