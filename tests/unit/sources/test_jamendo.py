"""Unit tests for sources.jamendo."""

from unittest.mock import patch

from sources import jamendo

_OK = {"headers": {"status": "success", "code": 0}}
_TRACK = {
    "id": 42,
    "name": "Song",
    "artist_name": "Band A",
    "audiodownload": "https://storage.test/download/42",
    "audiodownload_allowed": True,
    "shareurl": "https://jamendo.com/track/42",
    "license_ccurl": "https://cc/by-sa/3.0",
}


def test_maps_results_and_skips_non_downloadable(json_client):
    locked = {**_TRACK, "id": 43, "audiodownload_allowed": False}
    client, seen = json_client({**_OK, "results": [_TRACK, locked]})
    [track] = jamendo.find_tracks("Band A", "Song", client=client)
    assert (track.source_id, track.download_url) == ("42", _TRACK["audiodownload"])
    assert track.license_url == "https://cc/by-sa/3.0"
    params = seen[0].url.params
    assert (params["artist_name"], params["namesearch"]) == ("Band A", "Song")


def test_api_error_body_returns_empty(json_client):
    client, _ = json_client({"headers": {"status": "failed", "code": 5}, "results": []})
    assert jamendo.find_tracks("Band A", client=client) == []


def test_no_client_id_returns_empty():
    jamendo.default_client.cache_clear()
    with patch.object(jamendo.settings, "jamendo_client_id", ""):
        assert jamendo.find_tracks("Band A") == []
    jamendo.default_client.cache_clear()
