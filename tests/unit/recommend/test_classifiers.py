"""Unit tests for src/recommend/modules/classifiers.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import polars as pl
import pytest

from recommend.modules.classifiers import (
    CLASSIFIER_FEATURES,
    build_rerank_features,
    load_classifier,
    rerank_candidates,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_candidates(n: int = 10, seed: int = 0) -> pl.DataFrame:
    """Build a synthetic candidates DataFrame with all required columns."""
    rng = np.random.default_rng(seed)
    return pl.DataFrame(
        {
            "id": [f"track_{i:03d}" for i in range(n)],
            "track_name": [f"Track {i}" for i in range(n)],
            # SIMILARITY_FEATURES
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
            # Retrieval signals
            "similarity_score": rng.uniform(0.0, 1.0, n).tolist(),
            "cluster_prob": rng.uniform(0.0, 1.0, n).tolist(),
            # Categorical — needed for camelot_distance
            "key_mode": ["C Minor"] * n,
        }
    )


@pytest.fixture
def candidates() -> pl.DataFrame:
    return _make_candidates(n=10, seed=42)


@pytest.fixture
def playlist_profile() -> dict:
    return {
        "centroid": np.zeros(12),
        "modal_key": "G Minor",
        "mean_tempo": 120.0,
    }


# ---------------------------------------------------------------------------
# Tests for CLASSIFIER_FEATURES constant
# ---------------------------------------------------------------------------


class TestClassifierFeaturesConstant:
    def test_contains_similarity_features(self):
        from recommend.modules.similarity import SIMILARITY_FEATURES

        for feat in SIMILARITY_FEATURES:
            assert feat in CLASSIFIER_FEATURES

    def test_contains_retrieval_signals(self):
        for feat in ["similarity_score", "cluster_prob", "camelot_distance", "tempo_deviation"]:
            assert feat in CLASSIFIER_FEATURES

    def test_length(self):
        from recommend.modules.similarity import SIMILARITY_FEATURES

        assert len(CLASSIFIER_FEATURES) == len(SIMILARITY_FEATURES) + 4


# ---------------------------------------------------------------------------
# Tests for build_rerank_features
# ---------------------------------------------------------------------------


class TestBuildRerankFeatures:
    def test_raises_if_similarity_score_missing(self, playlist_profile):
        """ValueError when similarity_score column is absent."""
        df = _make_candidates(n=5, seed=1).drop("similarity_score")
        with pytest.raises(ValueError, match="similarity_score"):
            build_rerank_features(df, playlist_profile)

    def test_raises_if_cluster_prob_missing(self, playlist_profile):
        """ValueError when cluster_prob column is absent."""
        df = _make_candidates(n=5, seed=1).drop("cluster_prob")
        with pytest.raises(ValueError, match="cluster_prob"):
            build_rerank_features(df, playlist_profile)

    def test_returns_ndarray(self, candidates, playlist_profile):
        result = build_rerank_features(candidates, playlist_profile)
        assert isinstance(result, np.ndarray)

    def test_shape_n_rows(self, candidates, playlist_profile):
        result = build_rerank_features(candidates, playlist_profile)
        assert result.shape[0] == len(candidates)

    def test_dtype_float64(self, candidates, playlist_profile):
        result = build_rerank_features(candidates, playlist_profile)
        assert result.dtype == np.float64

    def test_camelot_distance_computed(self, playlist_profile):
        """Camelot distance column reflects harmonic distance to modal_key."""
        # C Minor -> G Minor distance is 1 on the Camelot wheel
        df = _make_candidates(n=3, seed=0)
        # All tracks have key_mode = "C Minor"; modal_key = "G Minor" -> distance 1
        X = build_rerank_features(df, playlist_profile)
        # camelot_distance is the second-to-last column (index -2)
        camelot_col = X[:, -2]
        assert np.all(camelot_col == 1.0)

    def test_tempo_deviation_computed(self, playlist_profile):
        """tempo_deviation = |track_tempo - mean_tempo|."""
        df = _make_candidates(n=3, seed=0)
        tempos = df["tempo"].to_numpy()
        X = build_rerank_features(df, playlist_profile)
        expected = np.abs(tempos - playlist_profile["mean_tempo"])
        np.testing.assert_allclose(X[:, -1], expected, rtol=1e-6)


# ---------------------------------------------------------------------------
# Tests for rerank_candidates — uses mock classifier (no real training)
# ---------------------------------------------------------------------------


class TestRerankCandidates:
    def _make_mock_classifier(self, n_rows: int, seed: int = 0) -> MagicMock:
        """Return a mock Pipeline whose predict_proba returns deterministic scores."""
        rng = np.random.default_rng(seed)
        scores = rng.uniform(0.0, 1.0, n_rows)

        mock = MagicMock()
        # predict_proba should return (n, 2) array; column 1 is the positive class prob
        mock.predict_proba.return_value = np.column_stack([1.0 - scores, scores])
        return mock

    def test_returns_polars_dataframe(self, candidates, playlist_profile):
        clf = self._make_mock_classifier(len(candidates))
        result = rerank_candidates(candidates, clf, playlist_profile)
        assert isinstance(result, pl.DataFrame)

    def test_adds_rerank_score_column(self, candidates, playlist_profile):
        clf = self._make_mock_classifier(len(candidates))
        result = rerank_candidates(candidates, clf, playlist_profile)
        assert "rerank_score" in result.columns

    def test_sorted_descending(self, candidates, playlist_profile):
        """rerank_score must be non-increasing from row 0 to last."""
        clf = self._make_mock_classifier(len(candidates), seed=7)
        result = rerank_candidates(candidates, clf, playlist_profile)
        scores = result["rerank_score"].to_numpy()
        assert np.all(scores[:-1] >= scores[1:]), "Scores are not sorted descending"

    def test_same_number_of_rows(self, candidates, playlist_profile):
        clf = self._make_mock_classifier(len(candidates))
        result = rerank_candidates(candidates, clf, playlist_profile)
        assert len(result) == len(candidates)

    def test_rerank_score_values_from_classifier(self, candidates, playlist_profile):
        """rerank_score values must come from predict_proba column 1."""
        fixed_scores = np.array([0.9, 0.1, 0.5, 0.7, 0.3, 0.8, 0.2, 0.6, 0.4, 0.0])
        mock = MagicMock()
        mock.predict_proba.return_value = np.column_stack(
            [1.0 - fixed_scores, fixed_scores]
        )
        result = rerank_candidates(candidates, mock, playlist_profile)
        expected_sorted = np.sort(fixed_scores)[::-1]
        np.testing.assert_allclose(
            result["rerank_score"].to_numpy(), expected_sorted, rtol=1e-6
        )


# ---------------------------------------------------------------------------
# Tests for load_classifier
# ---------------------------------------------------------------------------


class TestLoadClassifier:
    def test_returns_none_for_nonexistent_playlist(self, tmp_path):
        """No exception raised when the pkl file does not exist."""
        result = load_classifier("nonexistent_playlist", tmp_path)
        assert result is None

    def test_returns_none_for_missing_models_dir(self, tmp_path):
        """Non-existent models_dir: no crash, returns None."""
        missing_dir = tmp_path / "does_not_exist"
        result = load_classifier("any_slug", missing_dir)
        assert result is None

    def test_loads_saved_classifier(self, tmp_path):
        """Round-trip: save a real sklearn pipeline, load it back."""
        import joblib
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline as SkPipeline

        real_pipeline = SkPipeline([("clf", LogisticRegression())])
        slug = "test_playlist"
        joblib.dump(real_pipeline, tmp_path / f"classifier_{slug}.pkl")

        loaded = load_classifier(slug, tmp_path)
        assert loaded is not None
