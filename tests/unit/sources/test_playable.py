"""Unit tests for sources.youtube and sources.playable."""

import httpx

from sources import youtube
from sources.playable import resolve_playable


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
