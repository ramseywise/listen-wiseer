"""Unit tests for etl.history — Spotify privacy-export import into plays."""

import json
from pathlib import Path

import polars as pl
import pytest

from etl.history import import_history, load_plays, track_key

_EXTENDED = [
    {
        "ts": "2023-01-01T10:00:00Z",
        "ms_played": 240000,
        "master_metadata_track_name": "Song A",
        "master_metadata_album_artist_name": "Artist X",
        "master_metadata_album_album_name": "Album 1",
        "spotify_track_uri": "spotify:track:aaa",
        "skipped": False,
        "reason_end": "trackdone",
        "platform": "ios",  # extra keys ignored
    },
    {
        "ts": "2023-01-01T10:05:00Z",
        "ms_played": 5000,
        "master_metadata_track_name": "Song B",
        "master_metadata_album_artist_name": "Artist Y",
        "master_metadata_album_album_name": "Album 2",
        "spotify_track_uri": "spotify:track:bbb",
        "skipped": True,
        "reason_end": "fwdbtn",
    },
    {  # podcast episode → dropped
        "ts": "2023-01-01T11:00:00Z",
        "ms_played": 900000,
        "master_metadata_track_name": None,
        "master_metadata_album_artist_name": None,
        "master_metadata_album_album_name": None,
        "spotify_track_uri": None,
        "episode_name": "Some Pod",
    },
]

_ACCOUNT = [
    {"endTime": "2023-01-01 10:00", "artistName": "Artist X", "trackName": "Song A", "msPlayed": 1},
    {
        "endTime": "2024-02-02 08:30",
        "artistName": "Artist Z",
        "trackName": "Song C",
        "msPlayed": 200000,
    },
]


def _key_is(artist: str, title: str) -> pl.Expr:
    return pl.col("track_key") == track_key(artist, title)


@pytest.fixture
def export_dir(tmp_path: Path) -> Path:
    (tmp_path / "Streaming_History_Audio_2023_0.json").write_text(json.dumps(_EXTENDED))
    (tmp_path / "StreamingHistory_music_0.json").write_text(json.dumps(_ACCOUNT))
    (tmp_path / "StreamingHistory_podcast_0.json").write_text(json.dumps([{"podcastName": "x"}]))
    (tmp_path / "YourLibrary.json").write_text("{}")  # unrelated export file
    return tmp_path


class TestTrackKey:
    def test_normalises_case_and_whitespace(self):
        assert track_key("  Artist X ", "SONG a") == "artist x\tsong a"


class TestLoadPlays:
    def test_extended_rows_parsed_and_podcasts_dropped(self, export_dir):
        plays = load_plays(export_dir)
        a = plays.filter(plays["spotify_id"] == "aaa").row(0, named=True)
        assert a["track_key"] == track_key("Artist X", "Song A")
        assert a["album_name"] == "Album 1"
        assert a["skipped"] is False
        assert plays.filter(plays["spotify_id"] == "bbb")["skipped"].item() is True

    def test_account_rows_have_no_id_or_skip_info(self, export_dir):
        c = load_plays(export_dir).filter(_key_is("Artist Z", "Song C")).row(0, named=True)
        assert c["spotify_id"] is None
        assert c["skipped"] is None
        assert c["ms_played"] == 200000

    def test_extended_wins_on_collision(self, export_dir):
        plays = load_plays(export_dir)
        # Same (ts, track_key) in both files → one row, the extended one
        dupes = plays.filter(_key_is("Artist X", "Song A"))
        assert len(dupes) == 1
        assert dupes["spotify_id"].item() == "aaa"

    def test_total_rows(self, export_dir):
        # 2 extended music rows + 2 account rows - 1 collision
        assert len(load_plays(export_dir)) == 3

    def test_empty_dir(self, tmp_path):
        assert load_plays(tmp_path).is_empty()


class TestImportHistory:
    def test_inserts_and_is_idempotent(self, mem_conn, export_dir):
        plays = load_plays(export_dir)
        assert import_history(mem_conn, plays) == 3
        assert import_history(mem_conn, plays) == 0
        assert mem_conn.execute("SELECT count(*) FROM plays").fetchone()[0] == 3

    def test_empty_frame(self, mem_conn, tmp_path):
        assert import_history(mem_conn, load_plays(tmp_path)) == 0
