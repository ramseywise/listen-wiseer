"""Unit tests for src/recommend/modules/clustering.py."""

import numpy as np
import polars as pl
import pytest
from sklearn.preprocessing import MinMaxScaler

from utils.const import all_decades, all_key_modes
from recommend.modules.clustering import (
    CLUSTER_AUDIO_FEATURES,
    N_CLUSTER_FEATURES,
    build_cluster_features,
    filter_corpus_by_cluster,
    fit_gmm,
    predict_cluster_probs,
)


# ---------------------------------------------------------------------------
# Fixture: 20-row DataFrame with all required columns
# ---------------------------------------------------------------------------


def _make_corpus(n: int = 20, seed: int = 0) -> pl.DataFrame:
    """Build a synthetic corpus DataFrame for clustering tests.

    Includes all 11 audio features, top, left, key_mode, decade, id, track_name.
    """
    rng = np.random.default_rng(seed)

    n_key_modes = len(all_key_modes)
    n_decades = len(all_decades)

    return pl.DataFrame(
        {
            "id": [f"track_{i:03d}" for i in range(n)],
            "track_name": [f"Track {i}" for i in range(n)],
            # Continuous audio features (11 total)
            "danceability": rng.uniform(0.0, 1.0, n).tolist(),
            "energy": rng.uniform(0.0, 1.0, n).tolist(),
            "loudness": rng.uniform(-60.0, 0.0, n).tolist(),
            "speechiness": rng.uniform(0.0, 1.0, n).tolist(),
            "acousticness": rng.uniform(0.0, 1.0, n).tolist(),
            "instrumentalness": rng.uniform(0.0, 1.0, n).tolist(),
            "liveness": rng.uniform(0.0, 1.0, n).tolist(),
            "valence": rng.uniform(0.0, 1.0, n).tolist(),
            "tempo": rng.uniform(60.0, 200.0, n).tolist(),
            "top": rng.uniform(0.0, 5000.0, n).tolist(),
            "left": rng.uniform(0.0, 5000.0, n).tolist(),
            # Categorical columns using values from const.py
            "key_mode": [all_key_modes[i % n_key_modes] for i in range(n)],
            "decade": [all_decades[i % n_decades] for i in range(n)],
        }
    )


@pytest.fixture
def corpus() -> pl.DataFrame:
    return _make_corpus(n=20, seed=42)


# ---------------------------------------------------------------------------
# Tests for build_cluster_features
# ---------------------------------------------------------------------------


class TestBuildClusterFeatures:
    def test_returns_ndarray(self, corpus):
        scaler = MinMaxScaler()
        result, returned_scaler = build_cluster_features(
            corpus, scaler, fit_scaler=True
        )
        assert isinstance(result, np.ndarray)

    def test_shape_n_rows_matches(self, corpus):
        scaler = MinMaxScaler()
        result, _ = build_cluster_features(corpus, scaler, fit_scaler=True)
        assert result.shape[0] == len(corpus)

    def test_shape_n_features_correct(self, corpus):
        """Expected: 11 audio + 24 key_mode + 8 decade = 43 features."""
        scaler = MinMaxScaler()
        result, _ = build_cluster_features(corpus, scaler, fit_scaler=True)
        expected_n_features = (
            len(CLUSTER_AUDIO_FEATURES) + len(all_key_modes) + len(all_decades)
        )
        assert result.shape[1] == expected_n_features
        assert result.shape[1] == N_CLUSTER_FEATURES
        assert result.shape == (20, 43)

    def test_fit_scaler_true_returns_fitted_scaler(self, corpus):
        scaler = MinMaxScaler()
        _, returned_scaler = build_cluster_features(corpus, scaler, fit_scaler=True)
        # A fitted MinMaxScaler has data_min_ attribute
        assert hasattr(returned_scaler, "data_min_")

    def test_fit_scaler_false_uses_passed_scaler(self, corpus):
        """fit_scaler=False should transform without re-fitting."""
        scaler = MinMaxScaler()
        # Fit on full corpus first
        _, fitted_scaler = build_cluster_features(corpus, scaler, fit_scaler=True)

        # Now transform a subset using the pre-fit scaler
        subset = corpus.head(5)
        result, _ = build_cluster_features(subset, fitted_scaler, fit_scaler=False)
        assert result.shape == (5, N_CLUSTER_FEATURES)

    def test_values_scaled_between_0_and_1_for_audio_features(self, corpus):
        """MinMaxScaler applied to audio features should produce values in [0, 1]."""
        scaler = MinMaxScaler()
        result, _ = build_cluster_features(corpus, scaler, fit_scaler=True)
        # Audio feature columns only (first 11)
        audio_portion = result[:, : len(CLUSTER_AUDIO_FEATURES)]
        assert audio_portion.min() >= 0.0 - 1e-9
        assert audio_portion.max() <= 1.0 + 1e-9

    def test_one_hot_columns_are_binary(self, corpus):
        """One-hot encoded columns must be 0 or 1."""
        scaler = MinMaxScaler()
        result, _ = build_cluster_features(corpus, scaler, fit_scaler=True)
        ohe_portion = result[:, len(CLUSTER_AUDIO_FEATURES) :]
        unique_vals = np.unique(ohe_portion)
        # After MinMaxScaling, OHE columns that are all-zero stay 0;
        # columns with at least one 1 get scaled. The key check is all binary pre-scale.
        # We verify the raw OHE sum per row is exactly 2 (one key_mode + one decade).
        # Re-extract raw OHE to verify structure:
        from recommend.modules.clustering import _one_hot_encode

        km_ohe = _one_hot_encode(corpus, "key_mode", all_key_modes)
        dec_ohe = _one_hot_encode(corpus, "decade", all_decades)
        assert np.all((km_ohe == 0) | (km_ohe == 1))
        assert np.all((dec_ohe == 0) | (dec_ohe == 1))
        assert np.all(km_ohe.sum(axis=1) == 1)
        assert np.all(dec_ohe.sum(axis=1) == 1)


# ---------------------------------------------------------------------------
# Tests for fit_gmm
# ---------------------------------------------------------------------------


class TestFitGmm:
    def test_returns_gmm_and_scaler(self, corpus):
        gmm, scaler = fit_gmm(corpus, n_components=4, random_state=42)
        from sklearn.mixture import GaussianMixture

        assert isinstance(gmm, GaussianMixture)
        assert isinstance(scaler, MinMaxScaler)

    def test_gmm_n_components(self, corpus):
        gmm, _ = fit_gmm(corpus, n_components=4, random_state=42)
        assert gmm.n_components == 4

    def test_gmm_is_fitted(self, corpus):
        gmm, _ = fit_gmm(corpus, n_components=4, random_state=42)
        assert hasattr(gmm, "means_")


# ---------------------------------------------------------------------------
# Tests for predict_cluster_probs
# ---------------------------------------------------------------------------


class TestPredictClusterProbs:
    def test_shape(self, corpus):
        gmm, scaler = fit_gmm(corpus, n_components=4, random_state=42)
        features, _ = build_cluster_features(corpus, scaler, fit_scaler=False)
        probs = predict_cluster_probs(features, gmm)
        assert probs.shape == (len(corpus), 4)

    def test_rows_sum_to_one(self, corpus):
        gmm, scaler = fit_gmm(corpus, n_components=4, random_state=42)
        features, _ = build_cluster_features(corpus, scaler, fit_scaler=False)
        probs = predict_cluster_probs(features, gmm)
        np.testing.assert_allclose(probs.sum(axis=1), 1.0, atol=1e-6)

    def test_values_in_range(self, corpus):
        gmm, scaler = fit_gmm(corpus, n_components=4, random_state=42)
        features, _ = build_cluster_features(corpus, scaler, fit_scaler=False)
        probs = predict_cluster_probs(features, gmm)
        assert probs.min() >= 0.0
        assert probs.max() <= 1.0


# ---------------------------------------------------------------------------
# Tests for filter_corpus_by_cluster
# ---------------------------------------------------------------------------


class TestFilterCorpusByCluster:
    def test_returns_polars_dataframe(self, corpus):
        gmm, scaler = fit_gmm(corpus, n_components=4, random_state=42)
        features, _ = build_cluster_features(corpus, scaler, fit_scaler=False)
        query_probs = predict_cluster_probs(features[:1], gmm)[0]

        result = filter_corpus_by_cluster(
            corpus, query_probs, gmm, scaler, min_prob=0.05
        )
        assert isinstance(result, pl.DataFrame)

    def test_result_is_strict_subset_of_corpus(self, corpus):
        """Result must contain only rows present in the original corpus."""
        gmm, scaler = fit_gmm(corpus, n_components=4, random_state=42)
        features, _ = build_cluster_features(corpus, scaler, fit_scaler=False)
        # Use the first track as the query
        query_probs = predict_cluster_probs(features[:1], gmm)[0]

        result = filter_corpus_by_cluster(
            corpus, query_probs, gmm, scaler, min_prob=0.05
        )

        # All result IDs must appear in corpus IDs
        corpus_ids = set(corpus["id"].to_list())
        result_ids = set(result["id"].to_list())
        assert result_ids.issubset(corpus_ids)

        # Must be a non-empty subset (at least the query's own cluster is relevant)
        assert len(result) > 0

    def test_result_row_count_lte_corpus(self, corpus):
        """Filtered result must not exceed corpus size."""
        gmm, scaler = fit_gmm(corpus, n_components=4, random_state=42)
        features, _ = build_cluster_features(corpus, scaler, fit_scaler=False)
        query_probs = predict_cluster_probs(features[:1], gmm)[0]

        result = filter_corpus_by_cluster(
            corpus, query_probs, gmm, scaler, min_prob=0.05
        )
        assert len(result) <= len(corpus)

    def test_adds_cluster_id_column(self, corpus):
        gmm, scaler = fit_gmm(corpus, n_components=4, random_state=42)
        features, _ = build_cluster_features(corpus, scaler, fit_scaler=False)
        query_probs = predict_cluster_probs(features[:1], gmm)[0]

        result = filter_corpus_by_cluster(corpus, query_probs, gmm, scaler)
        assert "cluster_id" in result.columns

    def test_adds_cluster_prob_column(self, corpus):
        gmm, scaler = fit_gmm(corpus, n_components=4, random_state=42)
        features, _ = build_cluster_features(corpus, scaler, fit_scaler=False)
        query_probs = predict_cluster_probs(features[:1], gmm)[0]

        result = filter_corpus_by_cluster(corpus, query_probs, gmm, scaler)
        assert "cluster_prob" in result.columns

    def test_cluster_prob_values_in_range(self, corpus):
        gmm, scaler = fit_gmm(corpus, n_components=4, random_state=42)
        features, _ = build_cluster_features(corpus, scaler, fit_scaler=False)
        query_probs = predict_cluster_probs(features[:1], gmm)[0]

        result = filter_corpus_by_cluster(corpus, query_probs, gmm, scaler)
        probs = result["cluster_prob"].to_numpy()
        assert probs.min() >= 0.0
        assert probs.max() <= 1.0

    def test_min_prob_zero_returns_all_rows(self, corpus):
        """With min_prob=0.0, all clusters are relevant so all rows are returned."""
        gmm, scaler = fit_gmm(corpus, n_components=4, random_state=42)
        features, _ = build_cluster_features(corpus, scaler, fit_scaler=False)
        query_probs = predict_cluster_probs(features[:1], gmm)[0]

        result = filter_corpus_by_cluster(
            corpus, query_probs, gmm, scaler, min_prob=0.0
        )
        assert len(result) == len(corpus)

    def test_high_min_prob_returns_fewer_rows(self, corpus):
        """With very high min_prob, fewer rows are included."""
        gmm, scaler = fit_gmm(corpus, n_components=4, random_state=42)
        features, _ = build_cluster_features(corpus, scaler, fit_scaler=False)
        query_probs = predict_cluster_probs(features[:1], gmm)[0]

        result_loose = filter_corpus_by_cluster(
            corpus, query_probs, gmm, scaler, min_prob=0.0
        )
        result_strict = filter_corpus_by_cluster(
            corpus, query_probs, gmm, scaler, min_prob=0.5
        )
        assert len(result_strict) <= len(result_loose)

    def test_works_on_20_row_fixture_no_pkl(self):
        """End-to-end: 20-row fixture, no pkl required, fit_scaler=True inline."""
        corpus = _make_corpus(n=20, seed=7)
        gmm, scaler = fit_gmm(corpus, n_components=4, random_state=42)

        features, _ = build_cluster_features(corpus, scaler, fit_scaler=False)
        query_probs = predict_cluster_probs(features[:1], gmm)[0]

        result = filter_corpus_by_cluster(corpus, query_probs, gmm, scaler)

        corpus_ids = set(corpus["id"].to_list())
        result_ids = set(result["id"].to_list())
        assert result_ids.issubset(corpus_ids)
        assert "cluster_id" in result.columns
        assert "cluster_prob" in result.columns
