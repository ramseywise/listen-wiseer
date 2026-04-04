"""Unit tests for etl.sync — limits and include_in_refresh defaulting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from etl.db import init_schema
from etl.sync import (
    PlaylistSyncItem,
    sync_artist_features,
    sync_audio_features,
    sync_tracks,
    upsert_playlists,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(
    pid: str = "p1",
    name: str = "Playlist 1",
    spotify_count: int = 10,
    db_count: int = 0,
    is_new: bool = True,
    include: bool = True,
    last_synced: datetime | None = None,
) -> PlaylistSyncItem:
    return PlaylistSyncItem(
        playlist_id=pid,
        playlist_name=name,
        spotify_track_count=spotify_count,
        db_track_count=db_count,
        is_new=is_new,
        include_in_refresh=include,
        last_synced=last_synced,
    )


@pytest.fixture
def mem_conn():
    """In-memory DuckDB with full schema."""
    conn = duckdb.connect(":memory:")
    init_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# PlaylistSyncItem.needs_sync
# ---------------------------------------------------------------------------


class TestPlaylistSyncItemNeedsSync:
    def test_new_included_needs_sync(self):
        item = _make_item(is_new=True, include=True)
        assert item.needs_sync is True

    def test_excluded_never_needs_sync(self):
        item = _make_item(is_new=True, include=False)
        assert item.needs_sync is False

    def test_stale_count_needs_sync(self):
        item = _make_item(is_new=False, spotify_count=10, db_count=5, include=True)
        assert item.needs_sync is True

    def test_current_does_not_need_sync(self):
        item = _make_item(is_new=False, spotify_count=10, db_count=10, include=True)
        assert item.needs_sync is False

    def test_recently_synced_skipped(self):
        recent = datetime.now(UTC) - timedelta(hours=1)
        item = _make_item(is_new=True, include=True, last_synced=recent)
        assert item.needs_sync is False

    def test_old_sync_not_skipped(self):
        old = datetime.now(UTC) - timedelta(hours=24)
        item = _make_item(is_new=True, include=True, last_synced=old)
        assert item.needs_sync is True


# ---------------------------------------------------------------------------
# upsert_playlists — include_in_refresh defaulting
# ---------------------------------------------------------------------------


class TestUpsertPlaylists:
    def test_new_playlist_defaults_to_false(self, mem_conn):
        item = _make_item(pid="p_new", is_new=True, include=True)
        upsert_playlists(mem_conn, [item])
        row = mem_conn.execute(
            "SELECT include_in_refresh FROM playlists WHERE playlist_id = 'p_new'"
        ).fetchone()
        assert row is not None
        assert row[0] is False  # new playlists default to excluded

    def test_existing_playlist_keeps_true(self, mem_conn):
        # Pre-insert as bootstrapped (include_in_refresh=TRUE)
        mem_conn.execute(
            "INSERT INTO playlists (playlist_id, playlist_name, include_in_refresh) VALUES ('p_old', 'Old', TRUE)"
        )
        item = _make_item(pid="p_old", is_new=False, include=True)
        upsert_playlists(mem_conn, [item])
        row = mem_conn.execute(
            "SELECT include_in_refresh FROM playlists WHERE playlist_id = 'p_old'"
        ).fetchone()
        assert row[0] is True

    def test_upsert_preserves_existing_exclusion(self, mem_conn):
        mem_conn.execute(
            "INSERT INTO playlists (playlist_id, playlist_name, include_in_refresh) VALUES ('p_ex', 'Ex', FALSE)"
        )
        item = _make_item(pid="p_ex", is_new=False, include=False)
        upsert_playlists(mem_conn, [item])
        row = mem_conn.execute(
            "SELECT include_in_refresh FROM playlists WHERE playlist_id = 'p_ex'"
        ).fetchone()
        assert row[0] is False

    def test_multiple_playlists_upserted(self, mem_conn):
        items = [
            _make_item(pid="p1", is_new=True),
            _make_item(pid="p2", is_new=True),
        ]
        upsert_playlists(mem_conn, items)
        rows = mem_conn.execute("SELECT COUNT(*) FROM playlists").fetchone()
        assert rows[0] == 2


# ---------------------------------------------------------------------------
# sync_tracks — max_playlists + max_tracks limits
# ---------------------------------------------------------------------------


class TestSyncTracksLimits:
    def _fake_track(self, tid: str):
        t = MagicMock()
        t.id = tid
        t.name = f"Track {tid}"
        t.release_date = "2020-01-01"
        t.artist_ids = ["artist1"]
        return t

    def test_max_playlists_caps_synced(self, mem_conn):
        items = [_make_item(pid=f"p{i}", name=f"P{i}", is_new=True, include=True) for i in range(4)]
        client = MagicMock()
        client.get.return_value = {}
        with patch(
            "etl.sync.fetch_playlist_tracks",
            side_effect=lambda c, pid: [self._fake_track(f"{pid}_t")],
        ) as mock_fetch:
            sync_tracks(mem_conn, client, items, max_playlists=2)
        assert mock_fetch.call_count == 2

    def test_max_tracks_caps_total(self, mem_conn):
        items = [_make_item(pid=f"p{i}", name=f"P{i}", is_new=True, include=True) for i in range(3)]
        client = MagicMock()

        def _tracks(c, pid):
            return [self._fake_track(f"{pid}_t{j}") for j in range(3)]

        with patch("etl.sync.fetch_playlist_tracks", side_effect=_tracks):
            result = sync_tracks(mem_conn, client, items, max_tracks=4)
        assert len(result) <= 4

    def test_no_limits_syncs_all(self, mem_conn):
        items = [_make_item(pid=f"p{i}", name=f"P{i}", is_new=True, include=True) for i in range(3)]
        client = MagicMock()
        with patch(
            "etl.sync.fetch_playlist_tracks",
            side_effect=lambda c, pid: [self._fake_track(f"{pid}_t")],
        ) as mock_fetch:
            sync_tracks(mem_conn, client, items)
        assert mock_fetch.call_count == 3

    def test_excluded_playlists_not_synced(self, mem_conn):
        items = [
            _make_item(pid="p_inc", include=True, is_new=True),
            _make_item(pid="p_exc", include=False, is_new=True),
        ]
        client = MagicMock()
        with patch(
            "etl.sync.fetch_playlist_tracks",
            side_effect=lambda c, pid: [self._fake_track(f"{pid}_t")],
        ) as mock_fetch:
            sync_tracks(mem_conn, client, items)
        assert mock_fetch.call_count == 1


# ---------------------------------------------------------------------------
# sync_audio_features — limit
# ---------------------------------------------------------------------------


class TestSyncAudioFeaturesLimit:
    def test_limit_caps_missing_list(self, mem_conn):
        # Insert 5 tracks with no audio features
        for i in range(5):
            mem_conn.execute(
                "INSERT INTO tracks (track_id, track_name) VALUES (?, ?)",
                [f"t{i}", f"Track {i}"],
            )
        client = MagicMock()

        with patch("etl.sync.fetch_audio_features", return_value=[]) as mock_fetch:
            sync_audio_features(mem_conn, client, limit=2)

        called_ids = mock_fetch.call_args[0][1]
        assert len(called_ids) == 2

    def test_no_limit_passes_all_missing(self, mem_conn):
        for i in range(5):
            mem_conn.execute(
                "INSERT INTO tracks (track_id, track_name) VALUES (?, ?)",
                [f"t{i}", f"Track {i}"],
            )
        client = MagicMock()

        with patch("etl.sync.fetch_audio_features", return_value=[]) as mock_fetch:
            sync_audio_features(mem_conn, client)

        called_ids = mock_fetch.call_args[0][1]
        assert len(called_ids) == 5


# ---------------------------------------------------------------------------
# sync_artist_features — limit
# ---------------------------------------------------------------------------


class TestSyncArtistFeaturesLimit:
    def test_limit_caps_missing_list(self, mem_conn):
        # Insert tracks + track_artists with no artists table entries
        for i in range(5):
            mem_conn.execute(
                "INSERT INTO tracks (track_id, track_name) VALUES (?, ?)", [f"t{i}", f"T{i}"]
            )
            mem_conn.execute(
                "INSERT INTO track_artists (track_id, artist_id) VALUES (?, ?)",
                [f"t{i}", f"a{i}"],
            )
        client = MagicMock()

        with patch("etl.sync.fetch_artist_features", return_value=[]) as mock_fetch:
            sync_artist_features(mem_conn, client, limit=3)

        called_ids = mock_fetch.call_args[0][1]
        assert len(called_ids) == 3

    def test_no_limit_passes_all_missing(self, mem_conn):
        for i in range(5):
            mem_conn.execute(
                "INSERT INTO tracks (track_id, track_name) VALUES (?, ?)", [f"t{i}", f"T{i}"]
            )
            mem_conn.execute(
                "INSERT INTO track_artists (track_id, artist_id) VALUES (?, ?)",
                [f"t{i}", f"a{i}"],
            )
        client = MagicMock()

        with patch("etl.sync.fetch_artist_features", return_value=[]) as mock_fetch:
            sync_artist_features(mem_conn, client)

        called_ids = mock_fetch.call_args[0][1]
        assert len(called_ids) == 5
