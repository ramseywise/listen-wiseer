"""Fixtures for unit tests."""

import json
from pathlib import Path

import duckdb
import polars as pl
import pytest
from etl.db import init_schema


@pytest.fixture
def sample_tracks_df() -> pl.DataFrame:
    """Minimal playlist DataFrame with raw audio feature integers."""
    return pl.DataFrame(
        {
            "id": ["t1", "t2", "t3"],
            "track_name": ["Song A", "Song B", "Song C"],
            "release_date": ["1973-04-01", "1995-06-15", "2010-11-30"],
            "key": [7, 0, 11],
            "mode": [0, 1, 1],
            "genres": ["rock, classic rock", "jazz, bossa nova", "zouk"],
            "danceability": [0.5, 0.7, 0.9],
            "energy": [0.6, 0.4, 0.8],
            "tempo": [120.0, 90.0, 100.0],
            "valence": [0.4, 0.6, 0.7],
        }
    )


@pytest.fixture
def listening_history_dir(tmp_path: Path) -> Path:
    """Temp dir with two streaming history JSON files."""
    data = [
        {
            "ts": "2023-01-01T10:00:00Z",
            "ms_played": 240000,
            "master_metadata_track_name": "Song A",
            "master_metadata_album_artist_name": "Artist X",
            "master_metadata_album_album_name": "Album 1",
            "spotify_track_uri": "spotify:track:abc123",
            "reason_start": "clickrow",
            "reason_end": "trackdone",
            "skipped": False,
        },
        {
            "ts": "2023-01-01T10:05:00Z",
            "ms_played": 5000,
            "master_metadata_track_name": "Song B",
            "master_metadata_album_artist_name": "Artist Y",
            "master_metadata_album_album_name": "Album 2",
            "spotify_track_uri": "spotify:track:def456",
            "reason_start": "clickrow",
            "reason_end": "fwdbtn",
            "skipped": True,
        },
    ]
    (tmp_path / "StreamingHistory0.json").write_text(json.dumps(data))
    (tmp_path / "StreamingHistory1.json").write_text(json.dumps([data[0]]))
    return tmp_path


@pytest.fixture
def mem_conn() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with the full listen-wiseer schema (via init_schema)."""
    conn = duckdb.connect(":memory:")
    init_schema(conn)
    return conn
