"""Unit tests for agent.tools.discover — discovery, playback and local playlist tools."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import duckdb
import pytest

from agent.tools import discover as tools
from recommend.discover import Candidate
from sources.schemas import PlayableTrack, TrackRef


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


class TestSavePlaylist:
    TRACKS = [TrackRef(artist="A", title="x", mbid="m1")]

    def test_cancelled(self, fake_db):
        with patch.object(tools, "interrupt", return_value=False):
            assert "cancelled" in tools._save_local_playlist("Mix", self.TRACKS)
        assert tools._list_local_playlists() == "No saved playlists yet."

    def test_saves_and_exports(self, fake_db, tmp_path):
        with (
            patch.object(tools, "interrupt", return_value=True),
            patch.object(tools, "JSPF_DIR", tmp_path),
        ):
            out = tools._save_local_playlist("Mix", self.TRACKS)
        assert "Saved playlist 'Mix' with 1 tracks" in out
        [jspf] = tmp_path.glob("*.jspf")
        assert '"creator": "A"' in jspf.read_text()
        assert tools._list_local_playlists().startswith("Saved playlists:\n- Mix (1 tracks")


class TestListPlaylists:
    def test_lists_archived_but_not_excluded(self, fake_db):
        fake_db.execute(
            "INSERT INTO playlists (playlist_id, playlist_name, status) VALUES "
            "('p1', 'Zouk', 'archived'), ('p2', 'Junk', 'excluded')"
        )
        out = tools._list_local_playlists()
        assert out.startswith("No saved playlists yet.")
        assert "- Zouk" in out
        assert "Junk" not in out
