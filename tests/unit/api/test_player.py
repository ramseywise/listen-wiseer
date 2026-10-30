"""Unit tests for api.player — scrobble forwarding + ``plays`` rows, play-queue round trip."""

from datetime import datetime

import duckdb
import pytest

from api.player import record_play
from sources.subsonic import Song
from tests.unit.api.conftest import connect_to


def _plays(db_path) -> list[tuple]:
    conn = duckdb.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT track_key, track_name, artist_name, album_name, ms_played, skipped,"
            " navidrome_id, source, spotify_id FROM plays ORDER BY ts"
        ).fetchall()
    finally:
        conn.close()


class TestScrobble:
    def test_now_playing_forwards_only(self, nd_api, fake_nd, db_path):
        response = nd_api.post("/api/player/scrobble", json={"songId": "s1", "submission": False})
        assert response.status_code == 204
        assert fake_nd.scrobbles == [{"id": "s1", "submission": "false"}]
        assert _plays(db_path) == []

    def test_submission_forwards_and_records(self, nd_api, fake_nd, db_path):
        response = nd_api.post(
            "/api/player/scrobble",
            json={"songId": "s1", "submission": True, "playedSeconds": 123.4},
        )
        assert response.status_code == 204
        assert fake_nd.scrobbles == [{"id": "s1", "submission": "true"}]
        assert _plays(db_path) == [
            (
                "proleter\tapril showers",
                "April Showers",
                "ProleteR",
                "Album al1",
                123400,
                False,
                "s1",
                "navidrome",
                None,
            )
        ]

    def test_skip_is_recorded_not_forwarded(self, nd_api, fake_nd, db_path):
        nd_api.post(
            "/api/player/scrobble",
            json={"songId": "s3", "submission": True, "skipped": True, "playedSeconds": 4},
        )
        assert fake_nd.scrobbles == []
        assert [(r[1], r[4], r[5]) for r in _plays(db_path)] == [("Soul Key", 4000, True)]

    def test_unknown_song_is_404(self, nd_api, db_path):
        response = nd_api.post("/api/player/scrobble", json={"songId": "zz", "submission": True})
        assert response.status_code == 404
        assert _plays(db_path) == []

    def test_old_db_gets_new_columns(self, make_api, fake_nd, tmp_path):
        """A DB from before the player has ``plays`` without navidrome_id / source."""
        path = tmp_path / "old.db"
        conn = duckdb.connect(str(path))
        conn.execute(
            "CREATE TABLE plays (ts TIMESTAMP, track_key VARCHAR, spotify_id VARCHAR,"
            " track_name VARCHAR, artist_name VARCHAR, album_name VARCHAR, ms_played BIGINT,"
            " skipped BOOLEAN, reason_end VARCHAR, PRIMARY KEY (ts, track_key))"
        )
        conn.close()
        api = make_api(fake_nd, db_connect=connect_to(path))
        api.post("/api/player/scrobble", json={"songId": "s2", "submission": True})
        assert [(r[1], r[6], r[7]) for r in _plays(path)] == [("Downtown Irony", "s2", "navidrome")]

    def test_db_locked_still_204(self, make_api, fake_nd):
        def locked(read_only: bool = False) -> duckdb.DuckDBPyConnection:
            raise duckdb.IOException("Could not set lock on file")

        api = make_api(fake_nd, db_connect=locked)
        response = api.post("/api/player/scrobble", json={"songId": "s1", "submission": True})
        assert response.status_code == 204
        assert fake_nd.scrobbles == [{"id": "s1", "submission": "true"}]

    def test_requires_song_id(self, nd_api):
        assert nd_api.post("/api/player/scrobble", json={"submission": True}).status_code == 422


def test_record_play_title_whitespace_and_dedupe(db_path):
    song = Song.model_validate({"id": "x", "title": "  Spaced  ", "artist": "A"})
    ts = datetime(2026, 10, 30, 12)
    for _ in range(2):  # same (ts, track_key) → one row
        record_play(
            connect_to(db_path),
            song,
            played_seconds=None,
            skipped=False,
            ensure_schema=False,
            ts=ts,
        )
    assert [(r[0], r[1], r[3], r[4]) for r in _plays(db_path)] == [
        ("a\tspaced", "Spaced", None, None)
    ]


class TestQueue:
    def test_empty(self, nd_api):
        assert nd_api.get("/api/player/queue").json() == {"songIds": [], "position": 0, "songs": []}

    def test_round_trip_seconds(self, nd_api, fake_nd):
        body = {"songIds": ["s2", "s1"], "current": "s1", "position": 61.5}
        assert nd_api.put("/api/player/queue", json=body).status_code == 204
        assert fake_nd.queue is not None and fake_nd.queue["position"] == 61500
        got = nd_api.get("/api/player/queue").json()
        assert [s["id"] for s in got.pop("songs")] == ["s2", "s1"]
        assert got == body

    def test_current_not_in_queue_dropped(self, nd_api):
        nd_api.put("/api/player/queue", json={"songIds": ["s1"], "current": "s9", "position": 3})
        assert "current" not in nd_api.get("/api/player/queue").json()

    def test_put_empty_clears(self, nd_api, fake_nd):
        nd_api.put("/api/player/queue", json={"songIds": ["s1"], "current": "s1", "position": 0})
        nd_api.put("/api/player/queue", json={"songIds": []})
        assert fake_nd.queue is None

    @pytest.mark.parametrize("position", [-1, "x"])
    def test_bad_position_is_422(self, nd_api, position):
        response = nd_api.put("/api/player/queue", json={"songIds": [], "position": position})
        assert response.status_code == 422
