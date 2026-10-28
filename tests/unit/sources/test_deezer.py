"""Unit tests for sources.deezer."""

import httpx

from sources import deezer

_TRACK = {
    "id": 1,
    "title": "Weird Fishes / Arpeggi",
    "artist": {"name": "Band A"},
    "preview": "https://cdn/preview.mp3",
    "link": "https://www.deezer.com/track/1",
}


def _routed(make_client, routes: list[dict]):
    responses = iter(routes)
    return make_client(lambda _r: httpx.Response(200, json=next(responses)))


class TestFindTrack:
    def test_strict_query_hit(self, make_client):
        client = _routed(make_client, [{"data": [_TRACK]}])
        assert deezer.find_track("Band A", "Weird Fishes", client=client)["id"] == 1

    def test_falls_back_to_plain_query_and_checks_artist(self, make_client):
        other = {**_TRACK, "id": 2, "artist": {"name": "Covers Inc"}}
        client = _routed(make_client, [{"data": []}, {"data": [other, _TRACK]}])
        assert deezer.find_track("band a", "Weird Fishes", client=client)["id"] == 1

    def test_no_artist_match_returns_none(self, make_client):
        other = {**_TRACK, "artist": {"name": "Covers Inc"}}
        client = _routed(make_client, [{"data": []}, {"data": [other]}])
        assert deezer.find_track("Band A", "Weird Fishes", client=client) is None

    def test_api_error_body_returns_none(self, make_client):
        err = {"error": {"type": "Exception", "code": 4}}
        client = _routed(make_client, [err, err])
        assert deezer.find_track("Band A", "x", client=client) is None


class TestFindByIsrc:
    def test_hit(self, json_client):
        client, seen = json_client(_TRACK)
        assert deezer.find_by_isrc("GB123", client=client)["id"] == 1
        assert seen[0].url.path.endswith("/track/isrc:GB123")

    def test_error_body(self, json_client):
        client, _ = json_client({"error": {"code": 800}})
        assert deezer.find_by_isrc("GB123", client=client) is None


class TestRelatedArtists:
    def test_rank_derived_match(self, make_client):
        client = _routed(
            make_client,
            [{"data": [{"id": 399}]}, {"data": [{"name": "X"}, {"name": "Y"}]}],
        )
        items = deezer.related_artists("Band A", client=client)
        assert [i.artist for i in items] == ["X", "Y"]
        assert items[0].match == 1.0 and items[1].match == 0.5
        assert all(i.source == "deezer" for i in items)

    def test_unknown_artist(self, make_client):
        client = _routed(make_client, [{"data": []}])
        assert deezer.related_artists("nobody", client=client) == []
