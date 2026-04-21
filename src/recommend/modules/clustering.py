"""Soft GMM clustering for candidate filtering.

Replaces KMeans/Spectral from legacy code. Polars in, Polars out.
n_components=8 aligns with playlist_group_dict_8 in const.py.
"""

import numpy as np
import polars as pl
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import MinMaxScaler

from utils.const import all_decades, all_key_modes

# Audio features for clustering: SIMILARITY_FEATURES minus "popularity"
# (popularity is not a musical property and is excluded from cluster features)
CLUSTER_AUDIO_FEATURES: list[str] = [
    "danceability",
    "energy",
    "loudness",
    "speechiness",
    "acousticness",
    "instrumentalness",
    "liveness",
    "valence",
    "tempo",
    "top",
    "left",
    # Engineered features (Phase 3a)
    "fave_score",
    "n_playlists",
    "year_normalized",
    "duration_ms_normalized",
]

# Total feature count: 15 audio + 24 key_mode one-hot + 8 decade one-hot = 47
N_CLUSTER_FEATURES = len(CLUSTER_AUDIO_FEATURES) + len(all_key_modes) + len(all_decades)


def build_cluster_features(
    df: pl.DataFrame,
    scaler: MinMaxScaler,
    fit_scaler: bool = False,
) -> tuple[np.ndarray, MinMaxScaler]:
    """Extract, one-hot encode, and scale features for GMM clustering.

    Args:
        df: Input DataFrame with audio features, key_mode, and decade columns.
        scaler: Pre-fit MinMaxScaler for inference; fit here if fit_scaler=True.
        fit_scaler: If True, fit the scaler on df and return it fitted.
                    If False, transform using the passed (already-fit) scaler.

    Returns:
        Tuple of (scaled_feature_array, scaler).
        Array shape: (n_rows, 11 + 24 + 8) = (n_rows, 43).
    """
    # Extract continuous audio features
    audio_arr = df.select(CLUSTER_AUDIO_FEATURES).to_numpy().astype(np.float64)

    # One-hot encode key_mode (24 categories)
    key_mode_ohe = _one_hot_encode(df, "key_mode", all_key_modes)

    # One-hot encode decade (8 categories)
    decade_ohe = _one_hot_encode(df, "decade", all_decades)

    # Concatenate all features
    features = np.concatenate([audio_arr, key_mode_ohe, decade_ohe], axis=1)

    if fit_scaler:
        scaled = scaler.fit_transform(features)
    else:
        scaled = scaler.transform(features)

    return scaled, scaler


def _one_hot_encode(df: pl.DataFrame, col: str, categories: list[str]) -> np.ndarray:
    """One-hot encode a categorical column against a fixed list of categories.

    Args:
        df: Input DataFrame.
        col: Column name to encode.
        categories: Ordered list of all valid categories.

    Returns:
        Array of shape (n_rows, len(categories)) with 0/1 values.
    """
    n_rows = len(df)
    n_cats = len(categories)
    ohe = np.zeros((n_rows, n_cats), dtype=np.float64)

    col_values = df[col].to_list()
    cat_index = {cat: idx for idx, cat in enumerate(categories)}

    for row_idx, val in enumerate(col_values):
        if val in cat_index:
            ohe[row_idx, cat_index[val]] = 1.0

    return ohe


def fit_gmm(
    corpus: pl.DataFrame,
    n_components: int = 8,
    random_state: int = 42,
) -> tuple[GaussianMixture, MinMaxScaler]:
    """Fit a MinMaxScaler then a GaussianMixture on the corpus.

    n_components=8 aligns with playlist_group_dict_8 in const.py.
    Returns (gmm, scaler) tuple suitable for joblib serialization.

    Args:
        corpus: Full training corpus with audio features, key_mode, decade.
        n_components: Number of GMM components.
        random_state: Random seed for reproducibility.

    Returns:
        Tuple of (fitted_gmm, fitted_scaler).
    """
    scaler = MinMaxScaler()
    features, scaler = build_cluster_features(corpus, scaler, fit_scaler=True)

    gmm = GaussianMixture(
        n_components=n_components,
        random_state=random_state,
        covariance_type="full",
    )
    gmm.fit(features)

    return gmm, scaler


def predict_cluster_probs(
    features: np.ndarray,
    gmm: GaussianMixture,
) -> np.ndarray:
    """Predict soft cluster membership probabilities for each track.

    Args:
        features: Already-scaled feature array of shape (n_tracks, n_features).
        gmm: Fitted GaussianMixture model.

    Returns:
        Array of shape (n_tracks, n_components) with probabilities summing to 1 per row.
    """
    return gmm.predict_proba(features)


def filter_corpus_by_cluster(
    corpus: pl.DataFrame,
    query_probs: np.ndarray,
    gmm: GaussianMixture,
    scaler: MinMaxScaler,
    min_prob: float = 0.05,
) -> pl.DataFrame:
    """Return corpus rows whose dominant cluster overlaps the query cluster distribution.

    A corpus track is included if the query assigns probability >= min_prob to the
    track's dominant cluster (argmax of its own cluster probability vector).

    Adds 'cluster_id' (int, argmax cluster) and 'cluster_prob' (float, max prob) columns
    to the returned DataFrame.

    Args:
        corpus: Full candidate corpus with audio features, key_mode, decade.
        query_probs: Probability vector of shape (n_components,) from a single query track.
        gmm: Fitted GaussianMixture model.
        scaler: Fitted MinMaxScaler matching the GMM.
        min_prob: Minimum query probability for a cluster to be considered relevant.

    Returns:
        Subset of corpus rows whose dominant cluster is relevant to the query,
        with 'cluster_id' and 'cluster_prob' columns appended.
    """
    # Build and scale features for the entire corpus
    corpus_features, _ = build_cluster_features(corpus, scaler, fit_scaler=False)

    # Get soft assignments for all corpus tracks
    corpus_probs = predict_cluster_probs(corpus_features, gmm)

    # Dominant cluster per corpus track
    cluster_ids = np.argmax(corpus_probs, axis=1)
    cluster_probs_max = corpus_probs[np.arange(len(corpus_probs)), cluster_ids]

    # Relevant clusters: those where query has >= min_prob
    relevant_clusters = {int(c) for c in np.where(query_probs >= min_prob)[0]}

    # Build mask: include corpus tracks whose dominant cluster is relevant
    mask = np.array([int(cid) in relevant_clusters for cid in cluster_ids])

    filtered = corpus.filter(pl.Series(mask))
    cluster_ids_filtered = cluster_ids[mask]
    cluster_probs_filtered = cluster_probs_max[mask]

    filtered = filtered.with_columns(
        [
            pl.Series("cluster_id", cluster_ids_filtered.astype(np.int32)),
            pl.Series("cluster_prob", cluster_probs_filtered),
        ]
    )

    return filtered
