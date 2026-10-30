"""Unit tests for sources.youtube and sources.playable."""

import httpx
import pytest

from sources import youtube
from sources.playable import resolve_playable
from utils.exceptions import SourceError


class TestYoutube:
    def test_search_url_is_encoded(self):
        assert youtube.search_url("Sigur Rós", "Hoppípolla") == (
            "https://www.youtube.com/results?search_query=Sigur+R%C3%B3s+Hopp%C3%ADpolla"
        )

    def test_find_video_id(self, json_client):
        client, seen = json_client({"items": [{"id": {"videoId": "vid1"}}]})
        assert youtube.find_video_id("A", "B", client=client) == "vid1"
        assert seen[0].url.params["videoCategoryId"] == "10"

    def test_no_results(self, json_client):
        client, _ = json_client({"items": []})
        assert youtube.find_video_id("A", "B", client=client) is None

    def test_no_key_returns_none(self, monkeypatch):
        monkeypatch.setattr(youtube, "default_client", lambda: None)
        assert youtube.find_video_id("A", "B") is None


class TestResolvePlayable:
    def test_combines_deezer_and_youtube(self, json_client):
        dz, _ = json_client(
            {
                "data": [
                    {
                        "id": 7,
                        "link": "https://www.deezer.com/track/7",
                        "preview": "https://cdn/p.mp3",
                        "artist": {"name": "A"},
                    }
                ]
            }
        )
        yt, _ = json_client({"items": [{"id": {"videoId": "vid1"}}]})
        track = resolve_playable("A", "B", deezer_client=dz, youtube_client=yt)
        assert track.deezer_id == 7
        assert track.preview_url == "https://cdn/p.mp3"
        assert track.youtube_url == "https://www.youtube.com/watch?v=vid1"
        assert track.youtube_embed_url == "https://www.youtube.com/embed/vid1"

    def test_source_failures_fall_back_to_search_link(self, make_client, monkeypatch):
        monkeypatch.setattr(youtube, "default_client", lambda: None)
        broken = make_client(lambda _r: httpx.Response(500))
        track = resolve_playable("A", "B", deezer_client=broken)
        assert track.deezer_id is None
        assert track.preview_url == ""
        assert track.youtube_url.startswith("https://www.youtube.com/results?")


class TestYoutubeDefaultClient:
    def test_no_key_is_none(self, monkeypatch):
        youtube.default_client.cache_clear()
        monkeypatch.setattr(youtube.settings, "youtube_api_key", "")
        try:
            assert youtube.default_client() is None
        finally:
            youtube.default_client.cache_clear()

    def test_key_is_sent_as_default_param(self, monkeypatch):
        youtube.default_client.cache_clear()
        monkeypatch.setattr(youtube.settings, "youtube_api_key", "fake-key")
        try:
            client = youtube.default_client()
        finally:
            youtube.default_client.cache_clear()
        assert client is not None
        assert client.name == "youtube"
        assert client._default_params == {"key": "fake-key"}

    def test_error_status_raises(self, make_client):
        client = make_client(lambda _r: httpx.Response(403, json={"error": "quota"}))
        with pytest.raises(SourceError):
            youtube.find_video_id("A", "B", client=client)

    def test_url_helpers(self):
        assert youtube.watch_url("v") == "https://www.youtube.com/watch?v=v"
        assert youtube.embed_url("v") == "https://www.youtube.com/embed/v"


class TestResolvePlayableYoutubeFailure:
    def test_youtube_error_keeps_deezer_and_search_link(self, json_client, make_client):
        dz, _ = json_client({"data": [{"id": 9, "link": "l", "preview": "p", "isrc": "X1"}]})
        yt = make_client(lambda _r: httpx.Response(500))
        track = resolve_playable("A", "B", deezer_client=dz, youtube_client=yt)
        assert (track.deezer_id, track.isrc) == (9, "X1")
        assert track.youtube_url.startswith("https://www.youtube.com/results?")
        assert track.youtube_embed_url == ""

    def test_cached_video_id_skips_search(self, json_client):
        dz, _ = json_client({})
        yt, seen = json_client({"items": [{"id": {"videoId": "other"}}]})
        track = resolve_playable("A", "B", deezer_client=dz, youtube_client=yt, video_id="cached")
        assert track.youtube_url.endswith("v=cached")
        assert seen == []

    def test_search_disabled_leaves_search_link(self, json_client):
        dz, _ = json_client({})
        yt, seen = json_client({"items": [{"id": {"videoId": "vid"}}]})
        track = resolve_playable(
            "A", "B", deezer_client=dz, youtube_client=yt, search_youtube=False
        )
        assert track.youtube_url.startswith("https://www.youtube.com/results?")
        assert seen == []
