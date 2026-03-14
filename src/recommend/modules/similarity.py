"""Weighted cosine similarity with harmonic and tempo compatibility."""

from __future__ import annotations

import numpy as np
import polars as pl

SIMILARITY_FEATURES: list[str] = [
    "danceability",
    "energy",
    "loudness",
    "speechiness",
    "acousticness",
    "instrumentalness",
    "liveness",
    "valence",
    "tempo",
    "popularity",
    "top",
    "left",
]

DEFAULT_WEIGHTS: dict[str, float] = {f: 1.0 for f in SIMILARITY_FEATURES}

# Camelot wheel: key_mode string -> position 0-23
CAMELOT: dict[str, int] = {
    "Ab Minor": 0,
    "Eb Minor": 1,
    "Bb Minor": 2,
    "F Minor": 3,
    "C Minor": 4,
    "G Minor": 5,
    "D Minor": 6,
    "A Minor": 7,
    "E Minor": 8,
    "B Minor": 9,
    "F# Minor": 10,
    "Db Minor": 11,
    "B Major": 12,
    "F# Major": 13,
    "Db Major": 14,
    "Ab Major": 15,
    "Eb Major": 16,
    "Bb Major": 17,
    "F Major": 18,
    "C Major": 19,
    "G Major": 20,
    "D Major": 21,
    "A Major": 22,
    "E Major": 23,
}

_CAMELOT_SIZE = 24
_CAMELOT_MAX_DISTANCE = 6


def camelot_distance(a: str, b: str) -> int:
    """Harmonic distance between two key_mode strings (0=compatible, 6=max clash).

    Circular distance on 24-position Camelot wheel.
    Returns 6 if either key unknown.
    """
    pos_a = CAMELOT.get(a)
    pos_b = CAMELOT.get(b)
    if pos_a is None or pos_b is None:
        return _CAMELOT_MAX_DISTANCE
    diff = abs(pos_a - pos_b)
    circular = min(diff, _CAMELOT_SIZE - diff)
    return min(circular, _CAMELOT_MAX_DISTANCE)


def tempo_compatible(a: float, b: float, tolerance: float = 5.0) -> bool:
    """True if |a-b| <= tolerance OR half/double-time relationship within tolerance."""
    if abs(a - b) <= tolerance:
        return True
    # half-time: b ~ a/2
    if abs(a / 2.0 - b) <= tolerance:
        return True
    # double-time: b ~ a*2
    if abs(a * 2.0 - b) <= tolerance:
        return True
    return False


def compute_weighted_cosine(
    X: np.ndarray,
    query: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    """Compute weighted cosine similarity between query and each row of X.

    Args:
        X: (n_candidates, n_features) candidate feature matrix.
        query: (n_features,) query feature vector.
        weights: (n_features,) applied as sqrt(w) scaling before cosine.

    Returns:
        (n_candidates,) similarity scores in [0, 1].
    """
    scale = np.sqrt(np.maximum(weights, 0.0))
    X_scaled = X * scale
    q_scaled = query * scale

    X_norms = np.linalg.norm(X_scaled, axis=1)
    q_norm = np.linalg.norm(q_scaled)

    # Avoid division by zero
    denom = X_norms * q_norm
    safe_denom = np.where(denom == 0.0, 1.0, denom)

    similarities = np.dot(X_scaled, q_scaled) / safe_denom
    # Zero out cases where denom was 0
    similarities = np.where(denom == 0.0, 0.0, similarities)
    # Clip to [0, 1] — cosine can be negative; cap at 0 for non-negative interpretation
    return np.clip(similarities, 0.0, 1.0)


def playlist_centroid(features_df: pl.DataFrame, feature_cols: list[str]) -> np.ndarray:
    """Mean feature vector across playlist tracks.

    Args:
        features_df: DataFrame containing the playlist tracks.
        feature_cols: Column names to include in the centroid.

    Returns:
        (n_features,) mean vector.
    """
    return features_df.select(feature_cols).mean().to_numpy().flatten()


def find_similar(
    corpus: pl.DataFrame,
    query: np.ndarray,
    k: int,
    weights: dict[str, float] | None = None,
    exclude_ids: set[str] | None = None,
) -> pl.DataFrame:
    """Return top-k corpus rows by weighted cosine similarity.

    Adds a 'similarity_score' column. Results sorted descending by score.

    Args:
        corpus: Full candidate DataFrame; must contain all SIMILARITY_FEATURES columns.
        query: (n_features,) query vector aligned to SIMILARITY_FEATURES.
        k: Number of results to return.
        weights: Per-feature weights; defaults to DEFAULT_WEIGHTS if None.
        exclude_ids: Set of track IDs (from 'id' column) to exclude from results.

    Returns:
        DataFrame of up to k rows with 'similarity_score' column appended.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS

    # Filter excluded IDs
    df = corpus
    if exclude_ids and "id" in corpus.columns:
        df = corpus.filter(~pl.col("id").is_in(list(exclude_ids)))

    if df.is_empty():
        return df.with_columns(pl.lit(0.0).alias("similarity_score"))

    X = df.select(SIMILARITY_FEATURES).to_numpy().astype(np.float64)
    weight_arr = np.array([weights.get(f, 1.0) for f in SIMILARITY_FEATURES], dtype=np.float64)

    scores = compute_weighted_cosine(X, query.astype(np.float64), weight_arr)

    result = df.with_columns(pl.Series("similarity_score", scores))
    result = result.sort("similarity_score", descending=True)
    return result.head(k)
