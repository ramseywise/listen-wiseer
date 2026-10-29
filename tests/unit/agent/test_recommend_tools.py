"""Unit tests for agent.tools.recommend — name → corpus-ID lookups and engine routing."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from agent.tools import recommend
from recommend.schemas import RecommendResult


@pytest.fixture
def corpus_db(mem_conn):
    mem_conn.execute("""
        INSERT INTO tracks (track_id, track_name) VALUES ('t1', 'Reckoner');
        INSERT INTO artists (artist_id, artist_name) VALUES ('a1', 'Radiohead');
        INSERT INTO track_artists VALUES ('t1', 'a1');
        INSERT INTO external_tracks (track_id, track_name, artist_names)
            VALUES ('x1', 'Glory Box', 'Portishead');
        INSERT INTO playlists (playlist_id, playlist_name) VALUES
            ('p1', 'zouk'), ('p2', 'zouk love classics');
        INSERT INTO playlist_tracks (playlist_id, track_id, removed_at) VALUES
            ('p1', 't1', NULL), ('p1', 't2', now());
    """)  # fmt: skip

    @contextmanager
    def _db():
        yield mem_conn

    with patch.object(recommend, "db", _db):
        yield mem_conn


@pytest.fixture
def engine():
    eng = MagicMock()
    eng.recommend.return_value = RecommendResult(
        track_uris=["spotify:track:t9"], track_ids=["t9"], track_names=["Nude — Radiohead"],
        scores=[0.9], pipeline_used="track", explanation="Similar tracks",
    )  # fmt: skip
    with patch.object(recommend, "_engine", eng):
        yield eng


def _seed(engine: MagicMock) -> tuple[str, str]:
    req = engine.recommend.call_args.args[0]
    return req.request_type, req.seed_id


class TestLookups:
    def test_similar_tracks_case_insensitive(self, corpus_db, engine):
        out = recommend._recommend_similar_tracks("radiohead", "RECKONER")
        assert _seed(engine) == ("track", "t1")
        assert out == "Similar tracks\n\n1. Nude — Radiohead"

    def test_similar_tracks_falls_back_to_external(self, corpus_db, engine):
        recommend._recommend_similar_tracks("Portishead", "glory box")
        assert _seed(engine) == ("track", "x1")

    def test_similar_tracks_unknown(self, corpus_db, engine):
        assert "not in the local corpus" in recommend._recommend_similar_tracks("X", "y")
        engine.recommend.assert_not_called()

    def test_artist(self, corpus_db, engine):
        recommend._recommend_for_artist("RADIOHEAD")
        assert _seed(engine) == ("artist", "a1")

    def test_playlist_prefers_exact_name(self, corpus_db, engine):
        recommend._recommend_for_playlist("Zouk")
        assert _seed(engine) == ("playlist", "p1")

    def test_playlist_partial_match(self, corpus_db, engine):
        recommend._recommend_for_playlist("love")
        assert _seed(engine) == ("playlist", "p2")

    def test_playlist_track_ids_skip_removed(self, corpus_db):
        assert recommend._playlist_track_ids("p1") == ["t1"]


def test_engine_unavailable(corpus_db):
    with patch.object(recommend, "_engine", None):
        assert recommend._recommend_by_genre("zouk") == recommend._ENGINE_UNAVAILABLE
