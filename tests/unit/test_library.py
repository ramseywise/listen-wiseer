"""Unit tests for library — local playlists, JSPF export, cached playback resolution."""

import httpx

from etl.history import track_key
from library.playback import playable
from library.playlists import get_tracks, list_playlists, save_playlist, to_jspf
from sources.http import SourceClient
from sources.schemas import TrackRef


def _client(handler) -> SourceClient:
    return SourceClient("test", "https://api.test/", transport=httpx.MockTransport(handler))


TRACKS = [TrackRef(artist="A", title="One", mbid="m1"), TrackRef(artist="B", title="Two")]


class TestPlaylists:
    def test_round_trip_keeps_order(self, mem_conn):
        pid = save_playlist(mem_conn, "Mix", TRACKS, description="d")
        assert get_tracks(mem_conn, pid) == TRACKS

    def test_list_counts_tracks(self, mem_conn):
        pid = save_playlist(mem_conn, "Mix", TRACKS)
        [row] = list_playlists(mem_conn)
        assert (row["id"], row["name"], row["n_tracks"]) == (pid, "Mix", 2)

    def test_same_name_gets_new_id(self, mem_conn):
        assert save_playlist(mem_conn, "Mix", TRACKS) != save_playlist(mem_conn, "Mix", TRACKS)

    def test_unknown_playlist_empty(self, mem_conn):
        assert get_tracks(mem_conn, "nope") == []


class TestJspf:
    def test_shape(self):
        jspf = to_jspf("Mix", TRACKS, description="d")["playlist"]
        assert (jspf["title"], jspf["annotation"]) == ("Mix", "d")
        assert jspf["track"][0] == {
            "title": "One",
            "creator": "A",
            "identifier": ["https://musicbrainz.org/recording/m1"],
        }
        assert "identifier" not in jspf["track"][1]


def _deezer(_r: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"data": []})


class _YouTube:
    def __init__(self, video_id: str | None):
        self.calls = 0
        self.video_id = video_id

    def __call__(self, _r: httpx.Request) -> httpx.Response:
        self.calls += 1
        items = [{"id": {"videoId": self.video_id}}] if self.video_id else []
        return httpx.Response(200, json={"items": items})


class TestPlayable:
    def test_caches_video_id(self, mem_conn):
        yt = _YouTube("vid1")
        kw = {"conn": mem_conn, "deezer_client": _client(_deezer), "youtube_client": _client(yt)}
        first = playable("A", "One", **kw)
        second = playable("A", "One", **kw)
        assert (
            first.youtube_embed_url
            == second.youtube_embed_url
            == ("https://www.youtube.com/embed/vid1")
        )
        assert yt.calls == 1

    def test_caches_not_found(self, mem_conn):
        yt = _YouTube(None)
        kw = {"conn": mem_conn, "deezer_client": _client(_deezer), "youtube_client": _client(yt)}
        playable("A", "One", **kw)
        track = playable("A", "One", **kw)
        assert yt.calls == 1
        assert track.youtube_embed_url == ""
        assert track.youtube_url.startswith("https://www.youtube.com/results?")

    def test_cache_keyed_on_track_key(self, mem_conn):
        playable("A", "One", conn=mem_conn, deezer_client=_client(_deezer),
                 youtube_client=_client(_YouTube("vid1")))  # fmt: skip
        [(key, vid)] = mem_conn.execute(
            "SELECT track_key, youtube_video_id FROM playable_cache"
        ).fetchall()
        assert (key, vid) == (track_key("A", "One"), "vid1")

    def test_youtube_failure_not_cached(self, mem_conn):
        broken = _client(lambda _r: httpx.Response(500))
        track = playable("A", "One", conn=mem_conn, deezer_client=_client(_deezer),
                         youtube_client=broken)  # fmt: skip
        assert track.youtube_embed_url == ""
        assert mem_conn.execute("SELECT count(*) FROM playable_cache").fetchone() == (0,)
