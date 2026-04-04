"""Unit tests for etl.sync — limits and playlist status filtering."""

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
    status: str = "active",
    last_synced: datetime | None = None,
) -> PlaylistSyncItem:
    return PlaylistSyncItem(
        playlist_id=pid,
        playlist_name=name,
        spotify_track_count=spotify_count,
        db_track_count=db_count,
        is_new=is_new,
        playlist_status=status,
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
    def test_new_active_needs_sync(self):
        item = _make_item(is_new=True, status="active")
        assert item.needs_sync is True

    def test_excluded_never_needs_sync(self):
        item = _make_item(is_new=True, status="excluded")
        assert item.needs_sync is False

    def test_archived_never_needs_sync(self):
        item = _make_item(is_new=True, status="archived")
        assert item.needs_sync is False

    def test_stale_count_needs_sync(self):
        item = _make_item(is_new=False, spotify_count=10, db_count=5, status="active")
        assert item.needs_sync is True

    def test_current_does_not_need_sync(self):
        item = _make_item(is_new=False, spotify_count=10, db_count=10, status="active")
        assert item.needs_sync is False

    def test_recently_synced_skipped(self):
        recent = datetime.now(UTC) - timedelta(hours=1)
        item = _make_item(is_new=True, status="active", last_synced=recent)
        assert item.needs_sync is False

    def test_old_sync_not_skipped(self):
        old = datetime.now(UTC) - timedelta(hours=24)
        item = _make_item(is_new=True, status="active", last_synced=old)
        assert item.needs_sync is True


# ---------------------------------------------------------------------------
# PlaylistSyncItem.sync_status
# ---------------------------------------------------------------------------


class TestPlaylistSyncItemSyncStatus:
    def test_active_new(self):
        assert _make_item(is_new=True, status="active").sync_status == "new"

    def test_active_stale(self):
        assert (
            _make_item(is_new=False, spotify_count=10, db_count=5, status="active").sync_status
            == "stale"
        )

    def test_active_current(self):
        assert (
            _make_item(is_new=False, spotify_count=5, db_count=5, status="active").sync_status
            == "current"
        )

    def test_archived(self):
        assert _make_item(status="archived").sync_status == "archived"

    def test_excluded(self):
        assert _make_item(status="excluded").sync_status == "excluded"


# ---------------------------------------------------------------------------
# upsert_playlists — status written to DB
# ---------------------------------------------------------------------------


class TestUpsertPlaylists:
    def test_active_status_written(self, mem_conn):
        item = _make_item(pid="p_active", status="active")
        upsert_playlists(mem_conn, [item])
        row = mem_conn.execute(
            "SELECT status FROM playlists WHERE playlist_id = 'p_active'"
        ).fetchone()
        assert row is not None
        assert row[0] == "active"

    def test_archived_status_written(self, mem_conn):
        item = _make_item(pid="p_arch", status="archived")
        upsert_playlists(mem_conn, [item])
        row = mem_conn.execute(
            "SELECT status FROM playlists WHERE playlist_id = 'p_arch'"
        ).fetchone()
        assert row[0] == "archived"

    def test_excluded_status_written(self, mem_conn):
        item = _make_item(pid="p_exc", status="excluded")
        upsert_playlists(mem_conn, [item])
        row = mem_conn.execute(
            "SELECT status FROM playlists WHERE playlist_id = 'p_exc'"
        ).fetchone()
        assert row[0] == "excluded"

    def test_status_updated_on_conflict(self, mem_conn):
        mem_conn.execute(
            "INSERT INTO playlists (playlist_id, playlist_name, status) VALUES ('p1', 'P1', 'excluded')"
        )
        item = _make_item(pid="p1", is_new=False, status="active")
        upsert_playlists(mem_conn, [item])
        row = mem_conn.execute("SELECT status FROM playlists WHERE playlist_id = 'p1'").fetchone()
        assert row[0] == "active"

    def test_multiple_playlists_upserted(self, mem_conn):
        items = [_make_item(pid="p1"), _make_item(pid="p2")]
        upsert_playlists(mem_conn, items)
        count = mem_conn.execute("SELECT COUNT(*) FROM playlists").fetchone()[0]
        assert count == 2


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
        t.artist_names = ["Artist 1"]
        return t

    def test_max_playlists_caps_synced(self, mem_conn):
        items = [
            _make_item(pid=f"p{i}", name=f"P{i}", is_new=True, status="active") for i in range(4)
        ]
        client = MagicMock()
        with patch(
            "etl.sync.fetch_playlist_tracks",
            side_effect=lambda c, pid: [self._fake_track(f"{pid}_t")],
        ) as mock_fetch:
            sync_tracks(mem_conn, client, items, max_playlists=2)
        assert mock_fetch.call_count == 2

    def test_max_tracks_caps_total(self, mem_conn):
        items = [
            _make_item(pid=f"p{i}", name=f"P{i}", is_new=True, status="active") for i in range(3)
        ]
        client = MagicMock()

        def _tracks(c, pid):
            return [self._fake_track(f"{pid}_t{j}") for j in range(3)]

        with patch("etl.sync.fetch_playlist_tracks", side_effect=_tracks):
            result = sync_tracks(mem_conn, client, items, max_tracks=4)
        assert len(result) <= 4

    def test_no_limits_syncs_all(self, mem_conn):
        items = [
            _make_item(pid=f"p{i}", name=f"P{i}", is_new=True, status="active") for i in range(3)
        ]
        client = MagicMock()
        with patch(
            "etl.sync.fetch_playlist_tracks",
            side_effect=lambda c, pid: [self._fake_track(f"{pid}_t")],
        ) as mock_fetch:
            sync_tracks(mem_conn, client, items)
        assert mock_fetch.call_count == 3

    def test_excluded_playlists_not_synced(self, mem_conn):
        items = [
            _make_item(pid="p_inc", status="active", is_new=True),
            _make_item(pid="p_exc", status="excluded", is_new=True),
        ]
        client = MagicMock()
        with patch(
            "etl.sync.fetch_playlist_tracks",
            side_effect=lambda c, pid: [self._fake_track(f"{pid}_t")],
        ) as mock_fetch:
            sync_tracks(mem_conn, client, items)
        assert mock_fetch.call_count == 1

    def test_archived_playlists_not_synced(self, mem_conn):
        items = [
            _make_item(pid="p_act", status="active", is_new=True),
            _make_item(pid="p_arch", status="archived", is_new=True),
        ]
        client = MagicMock()
        with patch(
            "etl.sync.fetch_playlist_tracks",
            side_effect=lambda c, pid: [self._fake_track(f"{pid}_t")],
        ) as mock_fetch:
            sync_tracks(mem_conn, client, items)
        assert mock_fetch.call_count == 1

    def test_removed_tracks_marked_with_removed_at(self, mem_conn):
        """Tracks in DB but not returned by Spotify get removed_at set."""
        # Pre-insert a track as active member
        mem_conn.execute("INSERT INTO tracks (track_id, track_name) VALUES ('t_old', 'Old Track')")
        mem_conn.execute(
            "INSERT INTO playlist_tracks (playlist_id, track_id, removed_at) VALUES ('p1', 't_old', NULL)"
        )
        item = _make_item(pid="p1", is_new=False, spotify_count=1, db_count=2, status="active")
        client = MagicMock()
        # Spotify now returns a different track — t_old is gone
        with patch(
            "etl.sync.fetch_playlist_tracks",
            return_value=[self._fake_track("t_new")],
        ):
            sync_tracks(mem_conn, client, [item])

        row = mem_conn.execute(
            "SELECT removed_at FROM playlist_tracks WHERE playlist_id = 'p1' AND track_id = 't_old'"
        ).fetchone()
        assert row is not None
        assert row[0] is not None  # removed_at was set


# ---------------------------------------------------------------------------
# sync_audio_features — limit
# ---------------------------------------------------------------------------


class TestSyncAudioFeaturesLimit:
    def test_limit_caps_missing_list(self, mem_conn):
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
