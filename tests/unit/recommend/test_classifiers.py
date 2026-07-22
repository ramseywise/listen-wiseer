"""Unit tests for src/recommend/modules/classifiers.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import polars as pl
import pytest
from sklearn.mixture import GaussianMixture
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler

from recommend.modules.classifiers import (
    ALL_DECADES,
    ALL_GEN4,
    CATEGORICAL_FEATURES,
    CLASSIFIER_FEATURES,
    _compute_cluster_probs_for_corpus,
    _compute_similarity_scores_for_corpus,
    _create_estimator,
    _extract_categorical_features,
    _one_hot_column,
    build_rerank_features,
    load_classifier,
    rerank_candidates,
    train_playlist_classifier,
)
from utils.const import all_decades, all_key_modes

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
            # Categorical — needed for camelot_distance + CatBoost
            "key_mode": ["C Minor"] * n,
            "decade": rng.choice(all_decades, size=n).tolist(),
            "gen_4": rng.choice(ALL_GEN4, size=n).tolist(),
            # Engineered features (Phase 3a)
            "fave_score": rng.uniform(0.0, 5.0, n).tolist(),
            "n_playlists": rng.integers(0, 5, n).astype(float).tolist(),
            "year_normalized": rng.uniform(0.0, 1.0, n).tolist(),
            "embedding_similarity": rng.uniform(0.0, 1.0, n).tolist(),
            "playlist_diversity": rng.integers(0, 4, n).astype(float).tolist(),
        }
    )


def _make_train_corpus(n: int = 60, seed: int = 42) -> pl.DataFrame:
    """Synthetic corpus for training tests — includes clustering columns."""
    rng = np.random.default_rng(seed)
    return pl.DataFrame(
        {
            "id": [f"track_{i:04d}" for i in range(n)],
            "danceability": rng.uniform(0.0, 1.0, n).tolist(),
            "energy": rng.uniform(0.0, 1.0, n).tolist(),
            "loudness": rng.uniform(-60.0, 0.0, n).tolist(),
            "speechiness": rng.uniform(0.0, 0.5, n).tolist(),
            "acousticness": rng.uniform(0.0, 1.0, n).tolist(),
            "instrumentalness": rng.uniform(0.0, 1.0, n).tolist(),
            "liveness": rng.uniform(0.0, 1.0, n).tolist(),
            "valence": rng.uniform(0.0, 1.0, n).tolist(),
            "tempo": rng.uniform(60.0, 200.0, n).tolist(),
            "popularity": rng.integers(0, 100, n).tolist(),
            "top": rng.uniform(0.0, 5000.0, n).tolist(),
            "left": rng.uniform(0.0, 5000.0, n).tolist(),
            "key_mode": rng.choice(all_key_modes, size=n).tolist(),
            "decade": rng.choice(all_decades, size=n).tolist(),
            "gen_4": rng.choice(ALL_GEN4, size=n).tolist(),
            "fave_score": rng.uniform(0.0, 5.0, n).tolist(),
            "n_playlists": rng.integers(0, 5, n).astype(float).tolist(),
            "year_normalized": rng.uniform(0.0, 1.0, n).tolist(),
            "duration_ms_normalized": rng.uniform(0.0, 1.0, n).tolist(),
            "embedding_similarity": rng.uniform(0.0, 1.0, n).tolist(),
            "playlist_diversity": rng.integers(0, 4, n).astype(float).tolist(),
        }
    )


def _fit_gmm_and_scaler(corpus: pl.DataFrame) -> tuple[GaussianMixture, MinMaxScaler]:
    """Fit a small GMM + scaler on the synthetic corpus for testing."""
    from recommend.modules.clustering import fit_gmm

    return fit_gmm(corpus, n_components=4, random_state=42)


@pytest.fixture
def candidates() -> pl.DataFrame:
    return _make_candidates(n=10, seed=42)


@pytest.fixture
def playlist_profile() -> dict:
    return {
        "centroid": np.zeros(15),
        "modal_key": "G Minor",
        "mean_tempo": 120.0,
    }


@pytest.fixture
def train_corpus() -> pl.DataFrame:
    return _make_train_corpus(n=60)


@pytest.fixture
def gmm_and_scaler(train_corpus: pl.DataFrame) -> tuple[GaussianMixture, MinMaxScaler]:
    return _fit_gmm_and_scaler(train_corpus)


# ---------------------------------------------------------------------------
# Tests for CLASSIFIER_FEATURES constant
# ---------------------------------------------------------------------------


class TestClassifierFeaturesConstant:
    def test_contains_similarity_features(self):
        from recommend.modules.similarity import SIMILARITY_FEATURES

        for feat in SIMILARITY_FEATURES:
            assert feat in CLASSIFIER_FEATURES

    def test_contains_retrieval_signals(self):
        for feat in [
            "similarity_score",
            "cluster_prob",
            "camelot_distance",
            "tempo_deviation",
        ]:
            assert feat in CLASSIFIER_FEATURES

    def test_length(self):
        from recommend.modules.similarity import SIMILARITY_FEATURES

        assert len(CLASSIFIER_FEATURES) == len(SIMILARITY_FEATURES) + 6

    def test_categorical_features_defined(self):
        assert "decade" in CATEGORICAL_FEATURES
        assert "gen_4" in CATEGORICAL_FEATURES


# ---------------------------------------------------------------------------
# Tests for _one_hot_column
# ---------------------------------------------------------------------------


class TestOneHotColumn:
    def test_shape(self):
        values = ["acoustic", "dance", "acoustic"]
        result = _one_hot_column(values, ALL_GEN4)
        assert result.shape == (3, len(ALL_GEN4))

    def test_values(self):
        values = ["acoustic", "dance"]
        result = _one_hot_column(values, ALL_GEN4)
        # acoustic is index 0, dance is index 1
        assert result[0, 0] == 1.0
        assert result[1, 1] == 1.0
        assert result.sum() == 2.0

    def test_unknown_value_ignored(self):
        values = ["unknown_genre"]
        result = _one_hot_column(values, ALL_GEN4)
        assert result.sum() == 0.0


# ---------------------------------------------------------------------------
# Tests for _create_estimator
# ---------------------------------------------------------------------------


class TestCreateEstimator:
    def test_lightgbm(self):
        from lightgbm import LGBMClassifier

        est = _create_estimator("lightgbm")
        assert isinstance(est, LGBMClassifier)

    def test_catboost(self):
        from catboost import CatBoostClassifier

        est = _create_estimator("catboost")
        assert isinstance(est, CatBoostClassifier)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown model_type"):
            _create_estimator("xgboost")  # type: ignore[arg-type]


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

    def test_lightgbm_includes_onehot_categoricals(self, candidates, playlist_profile):
        """LightGBM path appends one-hot encoded decade (8) + gen_4 (4) = 12 extra cols."""
        result = build_rerank_features(candidates, playlist_profile, model_type="lightgbm")
        # Base 21 features + 8 decade OHE + 4 gen_4 OHE = 33
        assert result.shape[1] == 21 + len(ALL_DECADES) + len(ALL_GEN4)

    def test_catboost_excludes_categoricals(self, candidates, playlist_profile):
        """CatBoost path returns only the 21 numeric features (categoricals handled separately)."""
        result = build_rerank_features(candidates, playlist_profile, model_type="catboost")
        assert result.shape[1] == 21

    def test_camelot_distance_computed(self, playlist_profile):
        """Camelot distance column reflects harmonic distance to modal_key."""
        df = _make_candidates(n=3, seed=0)
        # All tracks have key_mode = "C Minor"; modal_key = "G Minor" -> distance 1
        X = build_rerank_features(df, playlist_profile, model_type="catboost")
        # For catboost (no OHE), camelot_distance is 4th from last
        camelot_col = X[:, -4]
        assert np.all(camelot_col == 1.0)

    def test_tempo_deviation_computed(self, playlist_profile):
        """tempo_deviation = |track_tempo - mean_tempo|."""
        df = _make_candidates(n=3, seed=0)
        tempos = df["tempo"].to_numpy()
        X = build_rerank_features(df, playlist_profile, model_type="catboost")
        expected = np.abs(tempos - playlist_profile["mean_tempo"])
        np.testing.assert_allclose(X[:, -3], expected, rtol=1e-6)


# ---------------------------------------------------------------------------
# Tests for _extract_categorical_features
# ---------------------------------------------------------------------------


class TestExtractCategoricalFeatures:
    def test_shape(self, candidates):
        result = _extract_categorical_features(candidates)
        assert result.shape == (len(candidates), len(CATEGORICAL_FEATURES))

    def test_values_are_strings(self, candidates):
        result = _extract_categorical_features(candidates)
        # All values should be strings
        for row in result:
            for val in row:
                assert isinstance(val, str)

    def test_missing_columns_use_unknown(self):
        df = pl.DataFrame({"id": ["t1", "t2"]})
        result = _extract_categorical_features(df)
        assert result.shape == (2, len(CATEGORICAL_FEATURES))
        assert all(val == "_unknown_" for val in result.flatten())


# ---------------------------------------------------------------------------
# Tests for _compute_cluster_probs_for_corpus
# ---------------------------------------------------------------------------


class TestComputeClusterProbs:
    def test_returns_1d_array(self, train_corpus, gmm_and_scaler):
        gmm, scaler = gmm_and_scaler
        result = _compute_cluster_probs_for_corpus(train_corpus, gmm, scaler)
        assert result.ndim == 1
        assert len(result) == len(train_corpus)

    def test_values_between_0_and_1(self, train_corpus, gmm_and_scaler):
        gmm, scaler = gmm_and_scaler
        result = _compute_cluster_probs_for_corpus(train_corpus, gmm, scaler)
        assert np.all(result >= 0.0)
        assert np.all(result <= 1.0)

    def test_values_nonzero(self, train_corpus, gmm_and_scaler):
        """cluster_prob should be non-zero for all tracks (every track has a dominant cluster)."""
        gmm, scaler = gmm_and_scaler
        result = _compute_cluster_probs_for_corpus(train_corpus, gmm, scaler)
        assert np.all(result > 0.0)


# ---------------------------------------------------------------------------
# Tests for _compute_similarity_scores_for_corpus
# ---------------------------------------------------------------------------


class TestComputeSimilarityScores:
    def test_returns_1d_array(self, train_corpus):
        playlist_ids = set(train_corpus["id"].head(20).to_list())
        result = _compute_similarity_scores_for_corpus(train_corpus, playlist_ids)
        assert result.ndim == 1
        assert len(result) == len(train_corpus)

    def test_values_between_0_and_1(self, train_corpus):
        playlist_ids = set(train_corpus["id"].head(20).to_list())
        result = _compute_similarity_scores_for_corpus(train_corpus, playlist_ids)
        assert np.all(result >= 0.0)
        assert np.all(result <= 1.0)

    def test_positives_have_nonzero_similarity(self, train_corpus):
        """Positive tracks should have non-zero similarity scores (they contribute to centroid)."""
        playlist_ids = set(train_corpus["id"].head(20).to_list())
        scores = _compute_similarity_scores_for_corpus(train_corpus, playlist_ids)
        pos_scores = scores[:20]
        # Positives formed the centroid — they should all have non-zero similarity
        assert np.all(pos_scores > 0.0)

    def test_empty_playlist_returns_zeros(self, train_corpus):
        scores = _compute_similarity_scores_for_corpus(train_corpus, set())
        assert np.all(scores == 0.0)


# ---------------------------------------------------------------------------
# Tests for train_playlist_classifier
# ---------------------------------------------------------------------------


class TestTrainPlaylistClassifier:
    @pytest.mark.parametrize("model_type", ["lightgbm", "catboost"])
    def test_returns_pipeline_and_metrics(self, train_corpus, gmm_and_scaler, model_type):
        gmm, gmm_scaler = gmm_and_scaler
        playlist_ids = set(train_corpus["id"].head(25).to_list())
        pipeline, metrics = train_playlist_classifier(
            corpus=train_corpus,
            playlist_track_ids=playlist_ids,
            scaler=MinMaxScaler(),
            gmm=gmm,
            gmm_scaler=gmm_scaler,
            model_type=model_type,
        )
        assert isinstance(pipeline, Pipeline)
        assert isinstance(metrics, dict)

    @pytest.mark.parametrize("model_type", ["lightgbm", "catboost"])
    def test_metrics_contain_all_keys(self, train_corpus, gmm_and_scaler, model_type):
        gmm, gmm_scaler = gmm_and_scaler
        playlist_ids = set(train_corpus["id"].head(25).to_list())
        _, metrics = train_playlist_classifier(
            corpus=train_corpus,
            playlist_track_ids=playlist_ids,
            scaler=MinMaxScaler(),
            gmm=gmm,
            gmm_scaler=gmm_scaler,
            model_type=model_type,
        )
        expected_keys = {
            "accuracy",
            "precision",
            "recall",
            "f1",
            "roc_auc",
            "precision_at_10",
            "brier_score",
            "log_loss",
        }
        assert expected_keys <= set(metrics.keys())

    @pytest.mark.parametrize("model_type", ["lightgbm", "catboost"])
    def test_brier_score_between_0_and_1(self, train_corpus, gmm_and_scaler, model_type):
        gmm, gmm_scaler = gmm_and_scaler
        playlist_ids = set(train_corpus["id"].head(25).to_list())
        _, metrics = train_playlist_classifier(
            corpus=train_corpus,
            playlist_track_ids=playlist_ids,
            scaler=MinMaxScaler(),
            gmm=gmm,
            gmm_scaler=gmm_scaler,
            model_type=model_type,
        )
        assert 0.0 <= metrics["brier_score"] <= 1.0

    def test_backward_compat_without_gmm(self, train_corpus):
        """Works without gmm/gmm_scaler (falls back to zero cluster_prob)."""
        playlist_ids = set(train_corpus["id"].head(25).to_list())
        pipeline, metrics = train_playlist_classifier(
            corpus=train_corpus,
            playlist_track_ids=playlist_ids,
            scaler=MinMaxScaler(),
        )
        assert isinstance(pipeline, Pipeline)
        assert "brier_score" in metrics

    @pytest.mark.parametrize("model_type", ["lightgbm", "catboost"])
    def test_pipeline_has_predict_proba(self, train_corpus, gmm_and_scaler, model_type):
        """Trained pipeline must support predict_proba for reranking."""
        gmm, gmm_scaler = gmm_and_scaler
        playlist_ids = set(train_corpus["id"].head(25).to_list())

        pipeline, _ = train_playlist_classifier(
            corpus=train_corpus,
            playlist_track_ids=playlist_ids,
            scaler=MinMaxScaler(),
            gmm=gmm,
            gmm_scaler=gmm_scaler,
            model_type=model_type,
        )
        assert hasattr(pipeline, "predict_proba")


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
        mock.predict_proba.return_value = np.column_stack([1.0 - fixed_scores, fixed_scores])
        result = rerank_candidates(candidates, mock, playlist_profile)
        expected_sorted = np.sort(fixed_scores)[::-1]
        np.testing.assert_allclose(result["rerank_score"].to_numpy(), expected_sorted, rtol=1e-6)


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
