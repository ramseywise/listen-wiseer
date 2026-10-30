"""Unit tests for etl.genre_tables — synthetic rows in an in-memory / tmp DuckDB."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from etl import genre_tables
from etl.db import init_schema

_EXTERNAL_COLS = [
    "id",
    "track_name",
    "artist_names",
    "popularity",
    "release_date",
    "year",
    "decade",
    "first_genre",
    "danceability",
    "energy",
    "loudness",
    "speechiness",
    "acousticness",
    "instrumentalness",
    "liveness",
    "valence",
    "tempo",
    "duration_ms",
    "time_signature",
    "key",
    "mode",
    "key_labels",
    "mode_labels",
    "key_mode",
    "top",
    "left",
    "color",
    "y_target",
]


def _seed(conn: duckdb.DuckDBPyConnection) -> None:
    """t1/t2 = zouk (genre_map), t3 = shoegaze (genre_xy only), t4 = unmapped."""
    conn.execute(
        "INSERT INTO genre_map VALUES "
        "('zouk', 'world', 'latin', 'caribbean', 'Zouk', 'kompa', 10.0, 20.0, '#f00')"
    )
    conn.execute("INSERT INTO genre_xy VALUES ('shoegaze', 30.0, 40.0, '#0f0')")
    conn.executemany(
        "INSERT INTO tracks (track_id, track_name, first_genre) VALUES (?, ?, ?)",
        [
            ("t1", "A", "zouk"),
            ("t2", "B", "zouk"),
            ("t3", "C", "shoegaze"),
            ("t4", "D", "mystery"),
        ],
    )
    conn.executemany(
        "INSERT INTO track_artists VALUES (?, ?)",
        [("t1", "ar1"), ("t2", "ar1"), ("t3", "ar1"), ("t4", "ar2")],
    )
    conn.executemany(
        "INSERT INTO playlist_tracks (playlist_id, track_id) VALUES (?, ?)",
        [("p1", "t1"), ("p1", "t2"), ("p1", "t3")],
    )


@pytest.fixture
def seeded(mem_conn: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    _seed(mem_conn)
    return mem_conn


def test_track_genre_assigns_source_by_match(seeded) -> None:
    genre_tables.populate_track_genre(seeded)
    rows = dict(
        seeded.execute("SELECT track_id, genre_source FROM track_genre ORDER BY 1").fetchall()
    )
    assert rows == {"t1": "manual", "t2": "manual", "t3": "lookup", "t4": "unknown"}


def test_track_genre_falls_back_to_genre_xy_coords(seeded) -> None:
    genre_tables.populate_track_genre(seeded)
    row = seeded.execute(
        "SELECT gen_4, top, \"left\", color FROM track_genre WHERE track_id = 't3'"
    ).fetchone()
    assert row == (None, 30.0, 40.0, "#0f0")


def test_artist_genre_aggregates_mode_centroid_and_dominant(seeded) -> None:
    genre_tables.populate_track_genre(seeded)
    genre_tables.populate_artist_genre(seeded)
    row = seeded.execute(
        'SELECT gen_4, my_genre, top, "left", dominant_genres, track_count '
        "FROM artist_genre WHERE artist_id = 'ar1'"
    ).fetchone()
    assert row is not None
    gen_4, my_genre, top, left, dominant, count = row
    assert (gen_4, my_genre, count) == ("world", "Zouk", 3)
    assert top == pytest.approx((10 + 10 + 30) / 3)
    assert left == pytest.approx((20 + 20 + 40) / 3)
    assert json.loads(dominant) == ["zouk", "shoegaze"]


def test_artist_genre_includes_unmapped_artist(seeded) -> None:
    genre_tables.populate_track_genre(seeded)
    genre_tables.populate_artist_genre(seeded)
    row = seeded.execute(
        "SELECT gen_4, top, track_count FROM artist_genre WHERE artist_id = 'ar2'"
    ).fetchone()
    assert row == (None, None, 1)


def test_playlist_genre_splits_top_and_other(seeded) -> None:
    genre_tables.populate_track_genre(seeded)
    genre_tables.populate_playlist_genre(seeded)
    row = seeded.execute(
        "SELECT gen_4, top_genres, other_genres, track_count FROM playlist_genre"
    ).fetchone()
    assert row is not None
    gen_4, top_genres, other_genres, count = row
    assert (gen_4, count) == ("world", 3)
    assert json.loads(top_genres) == ["zouk", "shoegaze"]
    assert json.loads(other_genres) == []


def test_load_external_tracks_missing_csv_is_noop(mem_conn, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(genre_tables, "EXTERNAL_CSV", tmp_path / "absent.csv")
    genre_tables.load_external_tracks(mem_conn)
    assert mem_conn.execute("SELECT COUNT(*) FROM external_tracks").fetchone() == (0,)


def _write_external_csv(path: Path) -> None:
    row = {
        "id": "x1",
        "track_name": "Ext",
        "artist_names": "Someone",
        "popularity": "50",
        "release_date": "2001-01-01",
        "year": "2001",
        "decade": "2000s",
        "first_genre": "zouk",
        "danceability": "0.5",
        "energy": "0.5",
        "loudness": "-5.0",
        "speechiness": "0.1",
        "acousticness": "0.2",
        "instrumentalness": "0.0",
        "liveness": "0.1",
        "valence": "0.6",
        "tempo": "100.0",
        "duration_ms": "200000",
        "time_signature": "4",
        "key": "5",
        "mode": "1",
        "key_labels": "F",
        "mode_labels": "major",
        "key_mode": "F major",
        "top": "10.0",
        "left": "20.0",
        "color": "#f00",
        "y_target": "1",
    }
    lines = [",".join(_EXTERNAL_COLS)]
    lines += [",".join(row[c] for c in _EXTERNAL_COLS)] * 2  # duplicate id → deduped
    path.write_text("\n".join(lines) + "\n")


def test_load_external_tracks_dedupes_ids(mem_conn, monkeypatch, tmp_path) -> None:
    csv = tmp_path / "train.csv"
    _write_external_csv(csv)
    monkeypatch.setattr(genre_tables, "EXTERNAL_CSV", csv)
    genre_tables.load_external_tracks(mem_conn)
    rows = mem_conn.execute("SELECT track_id, track_name, key FROM external_tracks").fetchall()
    assert rows == [("x1", "Ext", 5)]


def test_main_populates_all_tables(monkeypatch, tmp_path) -> None:
    db = tmp_path / "lw.duckdb"
    seed_conn = duckdb.connect(str(db))
    init_schema(seed_conn)
    _seed(seed_conn)
    seed_conn.close()

    monkeypatch.setattr(genre_tables, "get_connection", lambda: duckdb.connect(str(db)))
    monkeypatch.setattr(genre_tables, "EXTERNAL_CSV", tmp_path / "absent.csv")
    genre_tables.main()

    conn = duckdb.connect(str(db), read_only=True)
    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608
        for t in ("track_genre", "artist_genre", "playlist_genre")
    }
    conn.close()
    assert counts == {"track_genre": 4, "artist_genre": 2, "playlist_genre": 1}
