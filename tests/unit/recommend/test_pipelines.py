"""Unit tests for src/recommend/pipelines.py."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest
from recommend.modules.clustering import fit_gmm
from recommend.modules.similarity import SIMILARITY_FEATURES
from recommend.pipelines import (
    ArtistPipeline,
    GenrePipeline,
    PlaylistPipeline,
    TrackPipeline,
    _mmr_select,
)
from recommend.schemas import RecommendRequest, RecommendResult
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import MinMaxScaler

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_KEY_MODES = [
    "C Minor",
    "G Minor",
    "D Minor",
    "A Minor",
    "E Minor",
    "F Minor",
    "Bb Minor",
    "Eb Minor",
    "Ab Minor",
    "Db Minor",
    "F# Minor",
    "B Minor",
    "C Major",
    "G Major",
    "D Major",
    "A Major",
    "E Major",
    "F Major",
    "Bb Major",
    "Eb Major",
    "Ab Major",
    "Db Major",
    "F# Major",
    "B Major",
]
_DECADES = ["1960s", "1970s", "1980s", "1990s", "2000s", "2010s", "2020s", "1950s"]


def _make_corpus(n: int = 50, seed: int = 42) -> pl.DataFrame:
    """Build a 50-row synthetic corpus with all required columns.

    Columns: id, track_name, danceability, energy, loudness, speechiness,
    acousticness, instrumentalness, liveness, valence, tempo, popularity,
    top, left, key_mode, decade, artist_ids.
    """
    rng = np.random.default_rng(seed)
    return pl.DataFrame(
        {
            "id": [f"track_{i:03d}" for i in range(n)],
            "track_name": [f"Track {i}" for i in range(n)],
            "danceability": rng.uniform(0.0, 1.0, n).tolist(),
            "energy": rng.uniform(0.0, 1.0, n).tolist(),
            "loudness": rng.uniform(-60.0, 0.0, n).tolist(),
            "speechiness": rng.uniform(0.0, 1.0, n).tolist(),
            "acousticness": rng.uniform(0.0, 1.0, n).tolist(),
            "instrumentalness": rng.uniform(0.0, 1.0, n).tolist(),
            "liveness": rng.uniform(0.0, 1.0, n).tolist(),
            "valence": rng.uniform(0.0, 1.0, n).tolist(),
            "tempo": rng.uniform(60.0, 200.0, n).tolist(),
            "popularity": rng.integers(0, 100, n).tolist(),
            "top": rng.uniform(0.0, 5000.0, n).tolist(),
            "left": rng.uniform(0.0, 5000.0, n).tolist(),
            "key_mode": [_KEY_MODES[i % len(_KEY_MODES)] for i in range(n)],
            "decade": [_DECADES[i % len(_DECADES)] for i in range(n)],
            "artist_ids": [f"artist_{i % 10}" for i in range(n)],
            # Engineered features (Phase 3a)
            "fave_score": rng.uniform(0.0, 5.0, n).tolist(),
            "n_playlists": rng.integers(0, 5, n).astype(float).tolist(),
            "year_normalized": rng.uniform(0.0, 1.0, n).tolist(),
            "duration_ms_normalized": rng.uniform(0.0, 1.0, n).tolist(),
            "playlist_diversity": rng.integers(0, 4, n).astype(float).tolist(),
            "embedding_similarity": rng.uniform(0.0, 1.0, n).tolist(),
        }
    )


def _make_genre_map() -> pl.DataFrame:
    """Minimal genre_map with a known entry for 'test_genre'."""
    return pl.DataFrame(
        {
            "first_genre": ["test_genre", "zouk", "house", "jazz"],
            "top": [1000.0, 2500.0, 3000.0, 1500.0],
            "left": [1000.0, 2500.0, 3000.0, 1500.0],
        }
    )


@pytest.fixture(scope="module")
def corpus() -> pl.DataFrame:
    return _make_corpus(n=50, seed=42)


@pytest.fixture(scope="module")
def gmm_scaler(corpus) -> tuple[GaussianMixture, MinMaxScaler]:
    """Fit a real GMM + scaler on the fixture corpus."""
    return fit_gmm(corpus, n_components=4, random_state=42)


@pytest.fixture(scope="module")
def gmm(gmm_scaler) -> GaussianMixture:
    return gmm_scaler[0]


@pytest.fixture(scope="module")
def scaler(gmm_scaler) -> MinMaxScaler:
    return gmm_scaler[1]


@pytest.fixture(scope="module")
def query_features(corpus) -> np.ndarray:
    """SIMILARITY_FEATURES vector from the first corpus row."""
    return corpus.head(1).select(SIMILARITY_FEATURES).to_numpy().flatten().astype(np.float64)


@pytest.fixture(scope="module")
def genre_map() -> pl.DataFrame:
    return _make_genre_map()


# ---------------------------------------------------------------------------
# Tests for _mmr_select
# ---------------------------------------------------------------------------


class TestMmrSelect:
    def test_returns_at_most_k_rows(self, corpus, query_features):
        result = _mmr_select(corpus, query_features, k=5)
        assert len(result) <= 5

    def test_returns_all_when_candidates_lt_k(self, query_features):
        tiny = _make_corpus(n=3, seed=1)
        result = _mmr_select(tiny, query_features, k=10)
        assert len(result) == 3

    def test_returns_polars_dataframe(self, corpus, query_features):
        result = _mmr_select(corpus, query_features, k=5)
        assert isinstance(result, pl.DataFrame)

    def test_empty_candidates_returns_empty(self, corpus, query_features):
        empty = corpus.clear()
        result = _mmr_select(empty, query_features, k=5)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Tests for TrackPipeline
# ---------------------------------------------------------------------------


class TestTrackPipeline:
    def test_returns_recommend_result(self, corpus, gmm, scaler, query_features):
        pipeline = TrackPipeline()
        req = RecommendRequest(request_type="track", seed_id="track_000", k=5)
        result = pipeline.run(req, query_features, corpus, gmm, scaler)
        assert isinstance(result, RecommendResult)

    def test_track_uris_count_lte_k(self, corpus, gmm, scaler, query_features):
        pipeline = TrackPipeline()
        req = RecommendRequest(request_type="track", seed_id="track_000", k=5)
        result = pipeline.run(req, query_features, corpus, gmm, scaler)
        assert len(result.track_uris) <= 5

    def test_track_uris_format(self, corpus, gmm, scaler, query_features):
        pipeline = TrackPipeline()
        req = RecommendRequest(request_type="track", seed_id="track_000", k=5)
        result = pipeline.run(req, query_features, corpus, gmm, scaler)
        for uri in result.track_uris:
            assert uri.startswith("spotify:track:")

    def test_pipeline_used_is_track(self, corpus, gmm, scaler, query_features):
        pipeline = TrackPipeline()
        req = RecommendRequest(request_type="track", seed_id="track_000", k=5)
        result = pipeline.run(req, query_features, corpus, gmm, scaler)
        assert result.pipeline_used == "track"

    def test_track_ids_match_uris(self, corpus, gmm, scaler, query_features):
        pipeline = TrackPipeline()
        req = RecommendRequest(request_type="track", seed_id="track_000", k=5)
        result = pipeline.run(req, query_features, corpus, gmm, scaler)
        for uri, tid in zip(result.track_uris, result.track_ids, strict=False):
            assert uri == f"spotify:track:{tid}"

    def test_scores_length_matches_uris(self, corpus, gmm, scaler, query_features):
        pipeline = TrackPipeline()
        req = RecommendRequest(request_type="track", seed_id="track_000", k=5)
        result = pipeline.run(req, query_features, corpus, gmm, scaler)
        assert len(result.scores) == len(result.track_uris)

    def test_explanation_non_empty(self, corpus, gmm, scaler, query_features):
        pipeline = TrackPipeline()
        req = RecommendRequest(request_type="track", seed_id="track_000", k=5)
        result = pipeline.run(req, query_features, corpus, gmm, scaler)
        assert len(result.explanation) > 0


# ---------------------------------------------------------------------------
# Tests for ArtistPipeline
# ---------------------------------------------------------------------------


class TestArtistPipeline:
    def test_returns_recommend_result(self, corpus, gmm, scaler):
        # Use the first 3 tracks as the "artist's tracks"
        artist_tracks = corpus.head(3)
        pipeline = ArtistPipeline()
        req = RecommendRequest(request_type="artist", seed_id="artist_0", k=5)
        result = pipeline.run(req, artist_tracks, corpus, gmm, scaler)
        assert isinstance(result, RecommendResult)

    def test_track_uris_count_lte_k(self, corpus, gmm, scaler):
        artist_tracks = corpus.head(3)
        pipeline = ArtistPipeline()
        req = RecommendRequest(request_type="artist", seed_id="artist_0", k=5)
        result = pipeline.run(req, artist_tracks, corpus, gmm, scaler)
        assert len(result.track_uris) <= 5

    def test_track_uris_format(self, corpus, gmm, scaler):
        artist_tracks = corpus.head(3)
        pipeline = ArtistPipeline()
        req = RecommendRequest(request_type="artist", seed_id="artist_0", k=5)
        result = pipeline.run(req, artist_tracks, corpus, gmm, scaler)
        for uri in result.track_uris:
            assert uri.startswith("spotify:track:")

    def test_pipeline_used_is_artist(self, corpus, gmm, scaler):
        artist_tracks = corpus.head(3)
        pipeline = ArtistPipeline()
        req = RecommendRequest(request_type="artist", seed_id="artist_0", k=5)
        result = pipeline.run(req, artist_tracks, corpus, gmm, scaler)
        assert result.pipeline_used == "artist"

    def test_empty_artist_tracks_returns_empty(self, corpus, gmm, scaler):
        pipeline = ArtistPipeline()
        req = RecommendRequest(request_type="artist", seed_id="unknown_artist", k=5)
        result = pipeline.run(req, corpus.clear(), corpus, gmm, scaler)
        assert result.track_uris == []
        assert len(result.explanation) > 0

    def test_explanation_non_empty(self, corpus, gmm, scaler):
        artist_tracks = corpus.head(3)
        pipeline = ArtistPipeline()
        req = RecommendRequest(request_type="artist", seed_id="artist_0", k=5)
        result = pipeline.run(req, artist_tracks, corpus, gmm, scaler)
        assert len(result.explanation) > 0


# ---------------------------------------------------------------------------
# Tests for PlaylistPipeline
# ---------------------------------------------------------------------------


class TestPlaylistPipeline:
    def _make_playlist(self, corpus: pl.DataFrame, n: int = 5) -> pl.DataFrame:
        """Take the first n rows of corpus as the 'existing playlist'."""
        return corpus.head(n)

    def test_returns_recommend_result(self, corpus, gmm, scaler):
        playlist_tracks = self._make_playlist(corpus)
        pipeline = PlaylistPipeline()
        req = RecommendRequest(request_type="playlist", seed_id="playlist_abc", k=5)
        result = pipeline.run(req, playlist_tracks, corpus, gmm, scaler)
        assert isinstance(result, RecommendResult)

    def test_track_uris_count_lte_k(self, corpus, gmm, scaler):
        playlist_tracks = self._make_playlist(corpus)
        pipeline = PlaylistPipeline()
        req = RecommendRequest(request_type="playlist", seed_id="playlist_abc", k=5)
        result = pipeline.run(req, playlist_tracks, corpus, gmm, scaler)
        assert len(result.track_uris) <= 5

    def test_track_uris_format(self, corpus, gmm, scaler):
        playlist_tracks = self._make_playlist(corpus)
        pipeline = PlaylistPipeline()
        req = RecommendRequest(request_type="playlist", seed_id="playlist_abc", k=5)
        result = pipeline.run(req, playlist_tracks, corpus, gmm, scaler)
        for uri in result.track_uris:
            assert uri.startswith("spotify:track:")

    def test_pipeline_used_is_playlist(self, corpus, gmm, scaler):
        playlist_tracks = self._make_playlist(corpus)
        pipeline = PlaylistPipeline()
        req = RecommendRequest(request_type="playlist", seed_id="playlist_abc", k=5)
        result = pipeline.run(req, playlist_tracks, corpus, gmm, scaler)
        assert result.pipeline_used == "playlist"

    def test_excludes_playlist_track_ids(self, corpus, gmm, scaler):
        """No seed playlist track IDs should appear in the results."""
        playlist_tracks = self._make_playlist(corpus, n=10)
        seed_ids = set(playlist_tracks["id"].to_list())
        pipeline = PlaylistPipeline()
        req = RecommendRequest(request_type="playlist", seed_id="playlist_abc", k=10)
        result = pipeline.run(req, playlist_tracks, corpus, gmm, scaler)
        for tid in result.track_ids:
            assert tid not in seed_ids, f"Seed track {tid} should be excluded from results"

    def test_empty_playlist_returns_empty(self, corpus, gmm, scaler):
        pipeline = PlaylistPipeline()
        req = RecommendRequest(request_type="playlist", seed_id="playlist_empty", k=5)
        result = pipeline.run(req, corpus.clear(), corpus, gmm, scaler)
        assert result.track_uris == []
        assert len(result.explanation) > 0

    def test_explanation_non_empty(self, corpus, gmm, scaler):
        playlist_tracks = self._make_playlist(corpus)
        pipeline = PlaylistPipeline()
        req = RecommendRequest(request_type="playlist", seed_id="playlist_abc", k=5)
        result = pipeline.run(req, playlist_tracks, corpus, gmm, scaler)
        assert len(result.explanation) > 0


# ---------------------------------------------------------------------------
# Tests for GenrePipeline
# ---------------------------------------------------------------------------


class TestGenrePipeline:
    def test_returns_recommend_result(self, corpus, gmm, scaler, genre_map):
        pipeline = GenrePipeline()
        req = RecommendRequest(request_type="genre", seed_id="test_genre", k=5)
        # Use a large radius to capture all corpus rows (top/left spread up to 5000)
        result = pipeline.run(req, genre_map, corpus, gmm, scaler, enoa_radius=10000.0)
        assert isinstance(result, RecommendResult)

    def test_track_uris_count_lte_k(self, corpus, gmm, scaler, genre_map):
        pipeline = GenrePipeline()
        req = RecommendRequest(request_type="genre", seed_id="test_genre", k=5)
        result = pipeline.run(req, genre_map, corpus, gmm, scaler, enoa_radius=10000.0)
        assert len(result.track_uris) <= 5

    def test_track_uris_format(self, corpus, gmm, scaler, genre_map):
        pipeline = GenrePipeline()
        req = RecommendRequest(request_type="genre", seed_id="test_genre", k=5)
        result = pipeline.run(req, genre_map, corpus, gmm, scaler, enoa_radius=10000.0)
        for uri in result.track_uris:
            assert uri.startswith("spotify:track:")

    def test_pipeline_used_is_genre(self, corpus, gmm, scaler, genre_map):
        pipeline = GenrePipeline()
        req = RecommendRequest(request_type="genre", seed_id="test_genre", k=5)
        result = pipeline.run(req, genre_map, corpus, gmm, scaler, enoa_radius=10000.0)
        assert result.pipeline_used == "genre"

    def test_unknown_genre_returns_empty_uris(self, corpus, gmm, scaler, genre_map):
        pipeline = GenrePipeline()
        req = RecommendRequest(request_type="genre", seed_id="NONEXISTENT_GENRE_XYZ", k=5)
        result = pipeline.run(req, genre_map, corpus, gmm, scaler)
        assert result.track_uris == []

    def test_unknown_genre_has_non_empty_explanation(self, corpus, gmm, scaler, genre_map):
        pipeline = GenrePipeline()
        req = RecommendRequest(request_type="genre", seed_id="NONEXISTENT_GENRE_XYZ", k=5)
        result = pipeline.run(req, genre_map, corpus, gmm, scaler)
        assert len(result.explanation) > 0
        assert (
            "NONEXISTENT_GENRE_XYZ" in result.explanation
            or "not found" in result.explanation.lower()
        )

    def test_explanation_non_empty_for_known_genre(self, corpus, gmm, scaler, genre_map):
        pipeline = GenrePipeline()
        req = RecommendRequest(request_type="genre", seed_id="test_genre", k=5)
        result = pipeline.run(req, genre_map, corpus, gmm, scaler, enoa_radius=10000.0)
        assert len(result.explanation) > 0
