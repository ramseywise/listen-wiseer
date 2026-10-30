"""Unit tests for api.archive — archived Spotify playlists in a tmp DuckDB, copy via match."""

import duckdb
import pytest

from tests.unit.api.conftest import connect_to


@pytest.fixture
def archive_db(db_path):
    """Two archived playlists: 'Rainy' (3 tracks, one removed, one unmatched) and an empty one."""
    conn = duckdb.connect(str(db_path))
    conn.executemany(
        "INSERT INTO playlists (playlist_id, playlist_name) VALUES (?, ?)",
        [["p1", " Rainy "], ["p0", ""], ["p2", "acid"]],
    )
    conn.executemany(
        "INSERT INTO tracks (track_id, track_name) VALUES (?, ?)",
        [["t1", "Soul Key"], ["t2", "April Showers"], ["t3", "Gone Song"], ["t4", "Nothing Here"]],
    )
    conn.executemany(
        "INSERT INTO artists (artist_id, artist_name) VALUES (?, ?)",
        [["a1", "ProleteR"], ["a2", "Guest"], ["a3", "Nobody"]],
    )
    conn.executemany(
        "INSERT INTO track_artists VALUES (?, ?)",
        [["t1", "a1"], ["t1", "a2"], ["t2", "a1"], ["t3", "a1"], ["t4", "a3"]],
    )
    conn.executemany(
        "INSERT INTO playlist_tracks (playlist_id, track_id, removed_at) VALUES (?, ?, ?)",
        [
            ["p1", "t1", None],
            ["p1", "t3", "2025-01-01"],
            ["p1", "t4", None],
            ["p1", "t2", None],
        ],
    )
    conn.execute("INSERT INTO track_xref (track_key, spotify_id, mbid) VALUES ('k', 't2', 'mb-2')")
    conn.close()
    return db_path


@pytest.fixture
def arch_api(make_api, fake_nd, archive_db):
    return make_api(fake_nd, db_connect=connect_to(archive_db))


def test_list_counts_current_members_sorted(arch_api):
    assert arch_api.get("/api/archive/playlists").json() == [
        {"id": "p2", "name": "acid", "trackCount": 0},
        {"id": "p1", "name": "Rainy", "trackCount": 3},
        {"id": "p0", "name": "Untitled", "trackCount": 0},
    ]


def test_playlist_tracks_in_order_with_credits(arch_api):
    assert arch_api.get("/api/archive/playlists/p1").json() == {
        "id": "p1",
        "name": "Rainy",
        "tracks": [
            {"artist": "ProleteR, Guest", "title": "Soul Key"},
            {"artist": "Nobody", "title": "Nothing Here"},
            {"artist": "ProleteR", "title": "April Showers", "mbid": "mb-2"},
        ],
    }


def test_missing_playlist_is_404(arch_api):
    assert arch_api.get("/api/archive/playlists/nope").status_code == 404
    assert arch_api.post("/api/archive/playlists/nope/copy", json={}).status_code == 404


def test_db_locked_is_503(make_api, fake_nd):
    def locked(read_only: bool = False) -> duckdb.DuckDBPyConnection:
        raise duckdb.IOException("Could not set lock on file")

    response = make_api(fake_nd, db_connect=locked).get("/api/archive/playlists")
    assert response.status_code == 503


def test_copy_creates_library_playlist_and_reports_unmatched(arch_api, fake_nd):
    response = arch_api.post("/api/archive/playlists/p1/copy", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["playlist"]["name"] == "Rainy"
    assert [s["id"] for s in body["playlist"]["songs"]] == ["s3", "s1"]
    assert body["unmatched"] == [{"artist": "Nobody", "title": "Nothing Here"}]
    assert len(fake_nd.playlists) == 1


def test_copy_with_name_and_no_body(arch_api, fake_nd):
    named = arch_api.post("/api/archive/playlists/p1/copy", json={"name": "Rain 2"}).json()
    assert named["playlist"]["name"] == "Rain 2"
    assert arch_api.post("/api/archive/playlists/p2/copy").json()["playlist"]["songs"] == []


def test_copy_caches_matches_in_tmp_db(arch_api, archive_db):
    arch_api.post("/api/archive/playlists/p1/copy", json={})
    conn = duckdb.connect(str(archive_db))
    try:
        rows = conn.execute(
            "SELECT navidrome_id FROM track_xref WHERE navidrome_id IS NOT NULL ORDER BY 1"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("s1",), ("s3",)]
