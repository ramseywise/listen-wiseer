"""Unit tests for library — local playlists, JSPF export, playback resolution, downloads."""

from unittest.mock import patch

import httpx
import pytest
from mutagen.id3 import ID3, TPE1

from etl.history import track_key
from library import downloads
from library.playback import playable
from library.playlists import get_tracks, list_playlists, save_playlist, to_jspf
from sources.http import SourceClient
from sources.schemas import FreeTrack, TrackRef
from utils.exceptions import SourceError


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


FREE = FreeTrack(source="jamendo", source_id="42", artist="A/B", title="One?",
                 download_url="https://cdn.test/42", license_url="https://cc/by")  # fmt: skip


def _cdn(calls: list) -> SourceClient:
    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=b"mp3")

    return _client(handler)


class TestDownloads:
    def test_download_records_and_sanitises_path(self, mem_conn, tmp_path):
        calls: list = []
        path = downloads.download(mem_conn, FREE, mbid="m", library_dir=tmp_path,
                                  client=_cdn(calls))  # fmt: skip
        assert path == tmp_path / "A_B" / "One_.mp3"
        assert path.read_bytes().endswith(b"mp3")
        row = mem_conn.execute("SELECT mbid, source, license_url, path FROM library").fetchone()
        assert row == ("m", "jamendo", "https://cc/by", str(path))

    def test_existing_file_not_refetched(self, mem_conn, tmp_path):
        calls: list = []
        for _ in range(2):
            downloads.download(mem_conn, FREE, library_dir=tmp_path, client=_cdn(calls))
        assert len(calls) == 1

    def test_local_path_requires_file_on_disk(self, mem_conn, tmp_path):
        path = downloads.download(mem_conn, FREE, library_dir=tmp_path, client=_cdn([]))
        assert downloads.local_path(mem_conn, "a/b", "one?") == str(path)
        path.unlink()
        assert downloads.local_path(mem_conn, "A/B", "One?") is None

    def test_tags_mbid_licence_and_names(self, mem_conn, tmp_path):
        path = downloads.download(mem_conn, FREE, mbid="rec-1", library_dir=tmp_path,
                                  client=_cdn([]))  # fmt: skip
        tags = ID3(path)
        assert tags.getall("UFID")[0].data == b"rec-1"
        assert tags.getall("WCOP")[0].url == "https://cc/by"
        assert (str(tags["TPE1"]), str(tags["TIT2"])) == ("A/B", "One?")

    def test_existing_tags_kept(self, mem_conn, tmp_path):
        seed = tmp_path / "seed.mp3"
        seed.write_bytes(b"")
        tagged = ID3()
        tagged.add(TPE1(encoding=3, text="Original"))
        tagged.save(seed)
        body = seed.read_bytes() + b"audio"
        cdn = _client(lambda _r: httpx.Response(200, content=body))
        path = downloads.download(mem_conn, FREE, library_dir=tmp_path / "lib", client=cdn)
        assert str(ID3(path)["TPE1"]) == "Original"

    def test_requested_name_also_finds_file(self, mem_conn, tmp_path):
        path = downloads.download(mem_conn, FREE, requested=("A/B", "One"),
                                  library_dir=tmp_path, client=_cdn([]))  # fmt: skip
        assert downloads.local_path(mem_conn, "a/b", "one") == str(path)
        assert downloads.local_path(mem_conn, "A/B", "One?") == str(path)

    def test_find_free_skips_failing_source(self):
        def broken(*_a, **_k):
            raise SourceError("down")

        finders = (("jamendo", broken), ("archive_org", lambda *_a, **_k: [FREE]))
        with patch.object(downloads, "_FINDERS", finders):
            assert downloads.find_free("A/B") == [FREE]

    def test_playable_prefers_downloaded_file(self, mem_conn, tmp_path):
        path = downloads.download(mem_conn, FREE, library_dir=tmp_path, client=_cdn([]))
        track = playable("A/B", "One?", conn=mem_conn, deezer_client=_client(_deezer),
                         youtube_client=_client(_YouTube(None)))  # fmt: skip
        assert track.local_path == str(path)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("sources.http.time.sleep", lambda _s: None)
