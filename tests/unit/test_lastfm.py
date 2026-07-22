"""Unit tests for etl.lastfm and sync_lastfm_genres."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import duckdb
import pytest

from etl.lastfm import fetch_track_tags, match_genre
from etl.sync import sync_lastfm_genres

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_GENRE_XY_SEED = """
    INSERT INTO genre_xy (first_genre, top, "left", color) VALUES
    ('pop', 4997.0, 783.0, '#ad8907'),
    ('indie pop', 5100.0, 800.0, '#aa8800'),
    ('rock', 11552.0, 563.0, '#ac7119'),
    ('ambient', 15167.0, 234.0, '#4f94c4'),
    ('jazz', 9000.0, 400.0, '#336699')
"""


@pytest.fixture
def lastfm_conn(mem_conn: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """mem_conn with genre_xy seed data for Last.fm genre matching tests."""
    mem_conn.execute(_GENRE_XY_SEED)
    return mem_conn


# ---------------------------------------------------------------------------
# fetch_track_tags
# ---------------------------------------------------------------------------


class TestFetchTrackTags:
    def test_returns_tags_ordered_by_count(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "toptags": {
                "tag": [
                    {"name": "Pop", "count": "100"},
                    {"name": "Indie", "count": "50"},
                    {"name": "Noise", "count": "2"},  # below min_count=5
                ]
            }
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("etl.lastfm.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            tags = fetch_track_tags("Artist", "Title", "fakekey", min_count=5)

        assert tags == ["pop", "indie"]  # "noise" filtered, lowercased

    def test_single_tag_dict_normalised_to_list(self):
        """Last.fm returns a dict (not list) when there's only one tag."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"toptags": {"tag": {"name": "Jazz", "count": "80"}}}
        mock_resp.raise_for_status = MagicMock()

        with patch("etl.lastfm.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            tags = fetch_track_tags("Artist", "Title", "fakekey", min_count=5)

        assert tags == ["jazz"]

    def test_api_error_returns_empty(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": 6, "message": "Track not found"}
        mock_resp.raise_for_status = MagicMock()

        with patch("etl.lastfm.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            tags = fetch_track_tags("Unknown", "Unknown", "fakekey")

        assert tags == []

    def test_http_error_returns_empty(self):
        import httpx

        with patch("etl.lastfm.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.side_effect = httpx.HTTPError(
                "timeout"
            )
            tags = fetch_track_tags("Artist", "Title", "fakekey")

        assert tags == []


# ---------------------------------------------------------------------------
# match_genre
# ---------------------------------------------------------------------------


class TestMatchGenre:
    def test_first_matching_tag_returned(self):
        assert match_genre(["pop", "indie"], {"pop", "rock"}) == "pop"

    def test_second_tag_used_when_first_no_match(self):
        assert match_genre(["obscure-tag", "rock"], {"pop", "rock"}) == "rock"

    def test_no_match_returns_none(self):
        assert match_genre(["totally-unknown"], {"pop", "rock"}) is None

    def test_empty_tags_returns_none(self):
        assert match_genre([], {"pop", "rock"}) is None


# ---------------------------------------------------------------------------
# sync_lastfm_genres
# ---------------------------------------------------------------------------


class TestSyncLastfmGenres:
    def test_skips_when_no_api_key(self, lastfm_conn):
        with patch("etl.sync.settings") as mock_settings:
            mock_settings.lastfm_api_key = ""
            result = sync_lastfm_genres(lastfm_conn)
        assert result == 0

    def test_skips_when_genre_xy_empty(self, mem_conn):
        # genre_xy is empty (no bootstrap) — use base mem_conn, not lastfm_conn
        with patch("etl.sync.settings") as mock_settings:
            mock_settings.lastfm_api_key = "somekey"
            result = sync_lastfm_genres(mem_conn)
        assert result == 0

    def test_writes_first_genre_and_stub_audio_features(self, lastfm_conn):
        lastfm_conn.execute("""
            INSERT INTO tracks (track_id, track_name, release_date)
            VALUES ('t1', 'Blue in Green', '1959-01-01')
        """)

        with (
            patch("etl.sync.settings") as mock_settings,
            patch("etl.sync.fetch_genres_for_tracks") as mock_fetch,
        ):
            mock_settings.lastfm_api_key = "testkey"
            mock_fetch.return_value = {"t1": "jazz"}

            result = sync_lastfm_genres(lastfm_conn)

        assert result == 1
        genre = lastfm_conn.execute(
            "SELECT first_genre FROM tracks WHERE track_id = 't1'"
        ).fetchone()[0]
        assert genre == "jazz"
        src = lastfm_conn.execute(
            "SELECT features_source FROM audio_features WHERE track_id = 't1'"
        ).fetchone()[0]
        assert src == "lastfm"

    def test_no_match_leaves_first_genre_null(self, lastfm_conn):
        lastfm_conn.execute("""
            INSERT INTO tracks (track_id, track_name, release_date)
            VALUES ('t2', 'Unknown Track', '2020-01-01')
        """)

        with (
            patch("etl.sync.settings") as mock_settings,
            patch("etl.sync.fetch_genres_for_tracks") as mock_fetch,
        ):
            mock_settings.lastfm_api_key = "testkey"
            mock_fetch.return_value = {"t2": None}

            result = sync_lastfm_genres(lastfm_conn)

        assert result == 0
        genre = lastfm_conn.execute(
            "SELECT first_genre FROM tracks WHERE track_id = 't2'"
        ).fetchone()[0]
        assert genre is None
        af = lastfm_conn.execute(
            "SELECT track_id FROM audio_features WHERE track_id = 't2'"
        ).fetchone()
        assert af is None

    def test_limit_caps_tracks_processed(self, lastfm_conn):
        for i in range(5):
            lastfm_conn.execute(
                "INSERT INTO tracks (track_id, track_name, release_date) VALUES (?, ?, '2020-01-01')",
                [f"t{i}", f"Track {i}"],
            )

        with (
            patch("etl.sync.settings") as mock_settings,
            patch("etl.sync.fetch_genres_for_tracks") as mock_fetch,
        ):
            mock_settings.lastfm_api_key = "testkey"
            mock_fetch.return_value = {"t0": "pop", "t1": "rock"}

            sync_lastfm_genres(lastfm_conn, limit=2)

        # Only 2 tracks passed to fetch
        call_args = mock_fetch.call_args[0][0]
        assert len(call_args) == 2

    def test_does_not_overwrite_existing_audio_features(self, lastfm_conn):
        """Track already has audio_features row — INSERT OR IGNORE must not overwrite it."""
        lastfm_conn.execute("""
            INSERT INTO tracks (track_id, track_name, release_date)
            VALUES ('t3', 'Known Track', '2010-01-01')
        """)
        lastfm_conn.execute("""
            INSERT INTO audio_features (track_id, danceability, features_source)
            VALUES ('t3', 0.8, 'spotify')
        """)

        with (
            patch("etl.sync.settings") as mock_settings,
            patch("etl.sync.fetch_genres_for_tracks") as mock_fetch,
        ):
            mock_settings.lastfm_api_key = "testkey"
            mock_fetch.return_value = {"t3": "pop"}

            sync_lastfm_genres(lastfm_conn)

        src = lastfm_conn.execute(
            "SELECT features_source, danceability FROM audio_features WHERE track_id = 't3'"
        ).fetchone()
        # Existing spotify row preserved
        assert src[1] == 0.8
        assert src[0] == "spotify"
