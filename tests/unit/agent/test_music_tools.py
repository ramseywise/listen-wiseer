"""Unit tests for agent.tools.music — local listening history + free-source lookups."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from agent.tools import music
from sources.schemas import ArtistInfo, ArtistRelation, SimilarItem, TrackRef
from utils.exceptions import SourceError


@pytest.fixture
def fake_db(mem_conn):
    @contextmanager
    def _db():
        yield mem_conn

    with patch.object(music, "db", _db):
        yield mem_conn


def _play(conn, days_ago: int, artist: str, title: str, ms: int = 200_000) -> None:
    conn.execute(
        "INSERT INTO plays (ts, track_key, track_name, artist_name, ms_played) VALUES (?,?,?,?,?)",
        [datetime.now() - timedelta(days=days_ago), f"{artist}|{title}", title, artist, ms],
    )


@pytest.fixture
def history(fake_db):
    # Old favourite: 3 plays a year+ ago; new obsession: 2 recent plays; one skip.
    for d in (400, 401, 402):
        _play(fake_db, d, "Old Fave", "classic")
    _play(fake_db, 3, "New Thing", "hit")
    _play(fake_db, 5, "New Thing", "hit")
    _play(fake_db, 1, "Skipped", "nope", ms=5_000)
    return fake_db


class TestHistory:
    def test_empty_history_message(self, fake_db):
        assert music._get_top_tracks() == music._NO_HISTORY
        assert music._get_recently_played() == music._NO_HISTORY
        assert music._get_taste_analysis() == music._NO_HISTORY

    def test_recently_played_ignores_skips(self, history):
        out = music._get_recently_played()
        assert out.startswith("1. New Thing — hit")
        assert "Skipped" not in out

    def test_top_tracks_respects_period(self, history):
        assert "Old Fave" not in music._get_top_tracks("6m")
        assert music._get_top_tracks("all").startswith("1. Old Fave — classic (3 plays)")

    def test_top_artists(self, history):
        assert music._get_top_artists("all") == "1. Old Fave (3 plays)\n2. New Thing (2 plays)"

    def test_taste_analysis_rising_and_fading(self, history):
        out = music._get_taste_analysis()
        assert "Fading (all-time top, not recent): Old Fave" in out
        assert "Rising (recent, not all-time top): —" in out


class TestLookups:
    def test_search_tracks(self):
        hit = {
            "title": "Reckoner",
            "artist": {"name": "Radiohead"},
            "album": {"title": "In Rainbows"},
        }
        with patch.object(music.deezer, "search_tracks", return_value=[hit]):
            assert music._search_tracks("reckoner") == "1. Radiohead — Reckoner (In Rainbows)"

    def test_search_tracks_source_error(self):
        with patch.object(music.deezer, "search_tracks", side_effect=SourceError("down")):
            assert music._search_tracks("x").startswith("Search failed")

    def test_artist_info(self):
        info = ArtistInfo(
            mbid="m", name="Thom Yorke", type="Person", country="GB", begin="1968",
            genres=["art rock"],
            relations=[ArtistRelation(type="member of band", direction="forward",
                                      artist="Radiohead", mbid="r")],
        )  # fmt: skip
        with (
            patch.object(music.musicbrainz, "search_artist", return_value="m"),
            patch.object(music.musicbrainz, "get_artist", return_value=info),
        ):
            out = music._get_artist_info("Thom Yorke")
        assert out.splitlines()[0] == "Thom Yorke (Person, GB)"
        assert "Active: 1968 – present" in out
        assert "member of band: Radiohead" in out

    def test_artist_info_not_found(self):
        with patch.object(music.musicbrainz, "search_artist", return_value=None):
            assert "not found" in music._get_artist_info("Nobody")

    def test_related_artists_merges_sources_case_insensitively(self):
        lfm = [SimilarItem(source="lastfm", artist="Portishead", match=0.6),
               SimilarItem(source="lastfm", artist="Massive Attack", match=0.9)]  # fmt: skip
        dz = [SimilarItem(source="deezer", artist="portishead", match=0.5)]
        with (
            patch.object(music.lastfm, "similar_artists", return_value=lfm),
            patch.object(music.deezer, "related_artists", return_value=dz),
        ):
            assert music._get_related_artists("Tricky") == "1. Portishead\n2. Massive Attack"

    def test_related_artists_survives_one_source_failing(self):
        lfm = [SimilarItem(source="lastfm", artist="Portishead", match=0.6)]
        with (
            patch.object(music.lastfm, "similar_artists", return_value=lfm),
            patch.object(music.deezer, "related_artists", side_effect=SourceError("down")),
        ):
            assert music._get_related_artists("Tricky") == "1. Portishead"

    def test_artist_top_tracks_artifact(self):
        tracks = [TrackRef(artist="Radiohead", title="Creep", mbid="c")]
        with patch.object(music.lastfm, "artist_top_tracks", return_value=tracks):
            content, artifact = music._get_artist_top_tracks("Radiohead")
        assert content == "1. Radiohead — Creep"
        assert artifact == {"tracks": [{"artist": "Radiohead", "title": "Creep", "mbid": "c"}]}

    def test_artist_albums(self):
        albums = [{"title": "OK Computer", "date": "1997-05-21", "type": "Album"}]
        with (
            patch.object(music.musicbrainz, "search_artist", return_value="m"),
            patch.object(music.musicbrainz, "artist_albums", return_value=albums),
        ):
            assert music._get_artist_albums("Radiohead") == "- OK Computer (1997, Album)"
