"""Unit tests for sources.jamendo."""

from unittest.mock import patch

import httpx
import pytest

from sources import jamendo
from utils.exceptions import SourceError

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


def test_skips_tracks_without_download_url(json_client):
    no_url = {**_TRACK, "id": 44, "audiodownload": ""}
    client, _ = json_client({**_OK, "results": [no_url]})
    assert jamendo.find_tracks("Band A", client=client) == []


def test_artist_only_search_omits_namesearch(json_client):
    client, seen = json_client({**_OK, "results": [_TRACK]})
    [track] = jamendo.find_tracks("Band A", limit=3, client=client)
    params = seen[0].url.params
    assert "namesearch" not in params
    assert (params["limit"], params["audiodlformat"]) == ("3", "mp32")
    assert (track.source, track.page_url) == ("jamendo", _TRACK["shareurl"])


def test_optional_fields_default_to_empty(json_client):
    bare = {k: v for k, v in _TRACK.items() if k not in ("shareurl", "license_ccurl")}
    client, _ = json_client({**_OK, "results": [bare]})
    [track] = jamendo.find_tracks("Band A", client=client)
    assert (track.page_url, track.license_url) == ("", "")


def test_http_error_raises(make_client):
    client = make_client(lambda _r: httpx.Response(500))
    with pytest.raises(SourceError):
        jamendo.find_tracks("Band A", client=client)


def test_client_id_sent_as_default_param():
    jamendo.default_client.cache_clear()
    try:
        with patch.object(jamendo.settings, "jamendo_client_id", "fake-id"):
            client = jamendo.default_client()
    finally:
        jamendo.default_client.cache_clear()
    assert client is not None
    assert client._default_params == {"client_id": "fake-id", "format": "json"}
