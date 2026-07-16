"""Unit tests for src/recommend/modules/similarity.py."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest
from recommend.modules.similarity import (
    SIMILARITY_FEATURES,
    camelot_distance,
    compute_weighted_cosine,
    find_similar,
    playlist_centroid,
    tempo_compatible,
)
from sklearn.metrics.pairwise import cosine_similarity

# ---------------------------------------------------------------------------
# camelot_distance
# ---------------------------------------------------------------------------


def test_camelot_distance_adjacent() -> None:
    """C Minor (pos=4) and G Minor (pos=5): distance 1."""
    assert camelot_distance("C Minor", "G Minor") == 1


def test_camelot_distance_max() -> None:
    """C Minor (pos=4) and F# Minor (pos=10): diff=6 == max distance."""
    assert camelot_distance("C Minor", "F# Minor") == 6


def test_camelot_distance_unknown_key() -> None:
    """Unknown key string returns max distance 6."""
    assert camelot_distance("C Minor", "UNKNOWN") == 6


def test_camelot_distance_both_unknown() -> None:
    """Both unknown keys returns max distance 6."""
    assert camelot_distance("NOT_A_KEY", "UNKNOWN") == 6


def test_camelot_distance_same_key() -> None:
    """Same key -> distance 0."""
    assert camelot_distance("C Major", "C Major") == 0


def test_camelot_distance_circular() -> None:
    """Distance wraps around: Ab Minor (0) and E Major (23) -> distance min(23, 1) = 1."""
    assert camelot_distance("Ab Minor", "E Major") == 1


# ---------------------------------------------------------------------------
# tempo_compatible
# ---------------------------------------------------------------------------


def test_tempo_compatible_within_tolerance() -> None:
    """120.0 and 124.0 — difference 4 <= default tolerance 5."""
    assert tempo_compatible(120.0, 124.0) is True


def test_tempo_compatible_half_time() -> None:
    """120.0 and 60.5 — half-time: |120/2 - 60.5| = 0.5 <= 5."""
    assert tempo_compatible(120.0, 60.5) is True


def test_tempo_compatible_incompatible() -> None:
    """120.0 and 180.0 — diff=60, half=120, double=60, all > 5."""
    assert tempo_compatible(120.0, 180.0) is False


def test_tempo_compatible_exact_match() -> None:
    """Exact same tempo is always compatible."""
    assert tempo_compatible(128.0, 128.0) is True


def test_tempo_compatible_double_time() -> None:
    """120.0 and 240.5 — double-time: |120*2 - 240.5| = 0.5 <= 5."""
    assert tempo_compatible(120.0, 240.5) is True


def test_tempo_compatible_custom_tolerance() -> None:
    """With tight tolerance 1.0, diff=4 should be False."""
    assert tempo_compatible(120.0, 124.0, tolerance=1.0) is False


# ---------------------------------------------------------------------------
# compute_weighted_cosine
# ---------------------------------------------------------------------------


def _make_rng(seed: int = 0) -> np.random.Generator:
    return np.random.default_rng(seed)


def test_compute_weighted_cosine_uniform_matches_sklearn() -> None:
    """With uniform weights (all 1.0) the result must match sklearn cosine_similarity."""
    rng = _make_rng(42)
    n, d = 20, 12
    X = rng.random((n, d)).astype(np.float64)
    query = rng.random(d).astype(np.float64)
    weights = np.ones(d, dtype=np.float64)

    result = compute_weighted_cosine(X, query, weights)
    expected = cosine_similarity(X, query.reshape(1, -1)).flatten()
    # Clip expected to [0, 1] to match our implementation
    expected_clipped = np.clip(expected, 0.0, 1.0)

    np.testing.assert_allclose(result, expected_clipped, atol=1e-10)


def test_compute_weighted_cosine_shape() -> None:
    """Output shape is (n_candidates,)."""
    rng = _make_rng(1)
    X = rng.random((15, 12))
    query = rng.random(12)
    weights = np.ones(12)
    result = compute_weighted_cosine(X, query, weights)
    assert result.shape == (15,)


def test_compute_weighted_cosine_range() -> None:
    """All scores are in [0, 1]."""
    rng = _make_rng(2)
    X = rng.random((50, 12))
    query = rng.random(12)
    weights = rng.random(12)
    result = compute_weighted_cosine(X, query, weights)
    assert np.all(result >= 0.0)
    assert np.all(result <= 1.0)


def test_compute_weighted_cosine_identical_row() -> None:
    """A row identical to query with uniform weights should score 1.0."""
    d = 12
    query = np.ones(d, dtype=np.float64) * 0.5
    X = np.vstack([query, np.random.default_rng(3).random((9, d))])
    weights = np.ones(d, dtype=np.float64)
    result = compute_weighted_cosine(X, query, weights)
    assert pytest.approx(result[0], abs=1e-10) == 1.0


# ---------------------------------------------------------------------------
# playlist_centroid
# ---------------------------------------------------------------------------


def test_playlist_centroid_shape() -> None:
    """Centroid has length == len(feature_cols)."""
    rng = _make_rng(5)
    data = {col: rng.random(10).tolist() for col in SIMILARITY_FEATURES}
    df = pl.DataFrame(data)
    centroid = playlist_centroid(df, SIMILARITY_FEATURES)
    assert centroid.shape == (len(SIMILARITY_FEATURES),)


def test_playlist_centroid_single_row() -> None:
    """Centroid of a single row equals that row's values."""
    row = {col: [float(i)] for i, col in enumerate(SIMILARITY_FEATURES)}
    df = pl.DataFrame(row)
    centroid = playlist_centroid(df, SIMILARITY_FEATURES)
    expected = np.array([float(i) for i in range(len(SIMILARITY_FEATURES))])
    np.testing.assert_allclose(centroid, expected, atol=1e-10)


# ---------------------------------------------------------------------------
# find_similar
# ---------------------------------------------------------------------------


def _make_corpus(n: int = 30, seed: int = 7) -> pl.DataFrame:
    """Build a minimal corpus DataFrame with SIMILARITY_FEATURES and an 'id' column."""
    rng = np.random.default_rng(seed)
    data: dict[str, list] = {"id": [f"track_{i:03d}" for i in range(n)]}
    for col in SIMILARITY_FEATURES:
        data[col] = rng.random(n).tolist()
    return pl.DataFrame(data)


def test_find_similar_returns_k_rows() -> None:
    """find_similar returns exactly k rows when corpus has >= k rows."""
    corpus = _make_corpus(30)
    query = np.random.default_rng(8).random(len(SIMILARITY_FEATURES))
    result = find_similar(corpus, query, k=10)
    assert len(result) == 10


def test_find_similar_sorted_descending() -> None:
    """Rows are sorted by similarity_score in descending order."""
    corpus = _make_corpus(30)
    query = np.random.default_rng(9).random(len(SIMILARITY_FEATURES))
    result = find_similar(corpus, query, k=15)
    scores = result["similarity_score"].to_list()
    assert scores == sorted(scores, reverse=True)


def test_find_similar_excludes_seed_ids() -> None:
    """Excluded IDs are absent from results."""
    corpus = _make_corpus(30)
    query = np.random.default_rng(10).random(len(SIMILARITY_FEATURES))
    exclude = {"track_000", "track_001", "track_002"}
    result = find_similar(corpus, query, k=20, exclude_ids=exclude)
    returned_ids = set(result["id"].to_list())
    assert returned_ids.isdisjoint(exclude)


def test_find_similar_has_similarity_score_column() -> None:
    """Result DataFrame contains 'similarity_score' column."""
    corpus = _make_corpus(20)
    query = np.random.default_rng(11).random(len(SIMILARITY_FEATURES))
    result = find_similar(corpus, query, k=5)
    assert "similarity_score" in result.columns


def test_find_similar_k_larger_than_corpus() -> None:
    """When k > corpus size, returns all available rows."""
    corpus = _make_corpus(8)
    query = np.random.default_rng(12).random(len(SIMILARITY_FEATURES))
    result = find_similar(corpus, query, k=20)
    assert len(result) == 8


def test_find_similar_custom_weights() -> None:
    """Custom weights dict is accepted without error."""
    corpus = _make_corpus(20)
    query = np.random.default_rng(13).random(len(SIMILARITY_FEATURES))
    weights = dict.fromkeys(SIMILARITY_FEATURES, 2.0)
    result = find_similar(corpus, query, k=5, weights=weights)
    assert len(result) == 5
    assert "similarity_score" in result.columns
