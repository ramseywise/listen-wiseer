"""Unit tests for agent.tools.discover — discovery, playback and local playlist tools."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import duckdb
import pytest

from agent.tools import discover as tools
from library.navidrome_playlist import NavidromeNotConfigured, SavedPlaylist
from recommend.discover import Candidate
from sources.schemas import PlayableTrack, TrackRef
from sources.subsonic import PlaylistSummary, SubsonicUnavailable


@pytest.fixture
def fake_db(mem_conn):
    @contextmanager
    def _db():
        yield mem_conn

    with patch.object(tools, "db", _db):
        yield mem_conn


def _cand(artist: str, title: str, known: bool = False) -> Candidate:
    return Candidate(artist=artist, title=title, mbid="m", score=1.0,
                     sources=["lastfm", "listenbrainz"], known_artist=known)  # fmt: skip


class TestDiscoverTracks:
    def test_content_and_artifact(self, fake_db):
        with patch.object(tools, "discover", return_value=[_cand("A", "x", known=True)]):
            content, artifact = tools._discover_tracks("Seed")
        assert content == "1. A — x (lastfm+listenbrainz, known artist)"
        assert artifact == {"tracks": [{"artist": "A", "title": "x", "mbid": "m"}]}

    def test_locked_db_falls_back_without_history(self):
        @contextmanager
        def _locked():
            raise duckdb.IOException("lock")
            yield

        with (
            patch.object(tools, "db", _locked),
            patch.object(tools, "discover", return_value=[]) as disc,
        ):
            content, artifact = tools._discover_tracks("Seed")
        assert "conn" not in disc.call_args.kwargs
        assert (artifact, content) == ({}, "No similar tracks found for Seed.")


class TestPlayTrack:
    def test_formats_links(self, fake_db):
        p = PlayableTrack(artist="A", title="x", youtube_url="https://yt.test/w",
                          preview_url="https://dz.test/p.mp3")  # fmt: skip
        with patch.object(tools, "playable", return_value=p):
            content, artifact = tools._play_track("A", "x")
        assert "YouTube: https://yt.test/w" in content
        assert "30s preview: https://dz.test/p.mp3" in content
        assert artifact["playable"][0]["artist"] == "A"


@pytest.fixture
def no_navidrome():
    with patch.object(tools, "list_navidrome_playlists_sync", return_value=None):
        yield


class TestSavePlaylist:
    TRACKS = [TrackRef(artist="A", title="x", mbid="m1"), TrackRef(artist="B", title="y")]

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, no_navidrome):
        with (
            patch.object(tools, "JSPF_DIR", tmp_path),
            patch.object(tools, "match_cache", return_value=None),
        ):
            yield

    async def test_cancelled_writes_nothing(self, tmp_path):
        with (
            patch.object(tools, "interrupt", return_value=False),
            patch.object(tools, "save_to_navidrome", new_callable=AsyncMock) as save,
        ):
            text, artifact = await tools._save_playlist("Mix", self.TRACKS)
        assert (text, artifact) == ("Playlist 'Mix' creation cancelled.", {})
        save.assert_not_awaited()
        assert list(tmp_path.glob("*.jspf")) == []

    async def test_saves_to_navidrome_and_reports_unmatched(self, tmp_path):
        saved = SavedPlaylist(
            name="Mix", n_tracks=2, playlist_id="pl1", matched=1, unmatched=[self.TRACKS[1]]
        )
        with (
            patch.object(tools, "interrupt", return_value=True),
            patch.object(tools, "save_to_navidrome", new_callable=AsyncMock, return_value=saved),
        ):
            text, artifact = await tools._save_playlist("Mix", self.TRACKS)
        [jspf] = tmp_path.glob("*.jspf")
        assert '"creator": "A"' in jspf.read_text()
        assert "Saved playlist 'Mix'" in text and "1 of 2 tracks matched" in text
        assert "- B — y" in text and f"JSPF export: {jspf}" in text
        assert artifact == {"tracks": [{"artist": "B", "title": "y", "mbid": ""}]}

    async def test_navidrome_not_configured_keeps_jspf(self, tmp_path):
        boom = AsyncMock(side_effect=NavidromeNotConfigured("no creds"))
        with (
            patch.object(tools, "interrupt", return_value=True),
            patch.object(tools, "save_to_navidrome", boom),
        ):
            text, artifact = await tools._save_playlist("Mix", self.TRACKS)
        assert "Navidrome isn't configured" in text and "JSPF export:" in text
        assert artifact == {}
        assert len(list(tmp_path.glob("*.jspf"))) == 1

    async def test_navidrome_down_fails_cleanly(self):
        boom = AsyncMock(side_effect=SubsonicUnavailable("refused"))
        with (
            patch.object(tools, "interrupt", return_value=True),
            patch.object(tools, "save_to_navidrome", boom),
        ):
            text, _ = await tools._save_playlist("Mix", self.TRACKS)
        assert text.startswith("Failed to save playlist 'Mix' to the music library")


class TestListPlaylists:
    def test_lists_archived_but_not_excluded(self, fake_db, no_navidrome):
        fake_db.execute(
            "INSERT INTO playlists (playlist_id, playlist_name, status) VALUES "
            "('p1', 'Zouk', 'archived'), ('p2', 'Junk', 'excluded')"
        )
        out = tools._list_local_playlists()
        assert out.startswith("No saved playlists yet.")
        assert "- Zouk" in out
        assert "Junk" not in out

    def test_navidrome_playlists_first(self, fake_db):
        summary = PlaylistSummary(id="pl1", name="Mix", songCount=3)
        with patch.object(tools, "list_navidrome_playlists_sync", return_value=[summary]):
            out = tools._list_local_playlists()
        assert out == "Music library playlists:\n- Mix (3 tracks, id pl1)"
