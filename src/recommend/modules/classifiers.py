"""LightGBM binary reranker. One model per playlist. Calibrated probabilities."""

from __future__ import annotations

import re
from pathlib import Path

import joblib
import numpy as np
import polars as pl
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler

from recommend.modules.similarity import SIMILARITY_FEATURES, camelot_distance

CLASSIFIER_FEATURES: list[str] = SIMILARITY_FEATURES + [
    "similarity_score",
    "cluster_prob",
    "camelot_distance",
    "tempo_deviation",
]

_REQUIRED_RETRIEVAL_COLS = {"similarity_score", "cluster_prob"}


def _playlist_slug(name: str) -> str:
    """Convert a playlist name to a safe file slug.

    Lowercases, replaces spaces with underscores, strips non-alphanumeric
    characters except underscores.

    Examples:
        "Zoukini" -> "zoukini"
        "Lady Stardust" -> "lady_stardust"
        "Zapatos & Zapatos!" -> "zapatos__zapatos"
    """
    slug = name.lower().replace(" ", "_")
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    return slug


def build_rerank_features(
    candidates: pl.DataFrame,
    playlist_profile: dict,
) -> np.ndarray:
    """Build feature matrix for the reranker from a candidates DataFrame.

    Computes camelot_distance and tempo_deviation per-row using values from
    playlist_profile. Expects similarity_score and cluster_prob already present
    as columns on candidates.

    Args:
        candidates: DataFrame with SIMILARITY_FEATURES + similarity_score + cluster_prob.
        playlist_profile: Dict with keys: centroid, modal_key, mean_tempo.

    Returns:
        np.ndarray of shape (n_candidates, len(CLASSIFIER_FEATURES)).

    Raises:
        ValueError: If similarity_score or cluster_prob columns are missing.
    """
    missing = _REQUIRED_RETRIEVAL_COLS - set(candidates.columns)
    if missing:
        raise ValueError(
            f"candidates DataFrame is missing required columns: {sorted(missing)}"
        )

    modal_key: str = playlist_profile.get("modal_key", "")
    mean_tempo: float = float(playlist_profile.get("mean_tempo", 0.0))

    # Compute per-row derived features
    key_mode_col = (
        candidates["key_mode"].to_list()
        if "key_mode" in candidates.columns
        else [""] * len(candidates)
    )
    tempo_col = (
        candidates["tempo"].to_numpy()
        if "tempo" in candidates.columns
        else np.zeros(len(candidates))
    )

    camelot_dists = np.array(
        [camelot_distance(km, modal_key) for km in key_mode_col],
        dtype=np.float64,
    )
    tempo_devs = np.abs(tempo_col.astype(np.float64) - mean_tempo)

    # Build the full feature matrix column by column
    # First the base SIMILARITY_FEATURES
    base_cols = [c for c in SIMILARITY_FEATURES if c in candidates.columns]
    base_arr = candidates.select(base_cols).to_numpy().astype(np.float64)

    similarity_score = (
        candidates["similarity_score"].to_numpy().astype(np.float64).reshape(-1, 1)
    )
    cluster_prob = (
        candidates["cluster_prob"].to_numpy().astype(np.float64).reshape(-1, 1)
    )

    X = np.concatenate(
        [
            base_arr,
            similarity_score,
            cluster_prob,
            camelot_dists.reshape(-1, 1),
            tempo_devs.reshape(-1, 1),
        ],
        axis=1,
    )
    return X


def train_playlist_classifier(
    corpus: pl.DataFrame,
    playlist_track_ids: set[str],
    scaler: MinMaxScaler,
    max_negatives: int = 5000,
) -> tuple[Pipeline, dict]:
    """Train a LightGBM classifier for a single playlist.

    Derives binary y_target from playlist_track_ids membership.
    Wraps LGBMClassifier in CalibratedClassifierCV (isotonic, cv=5).

    Args:
        corpus: Full training corpus; must contain all SIMILARITY_FEATURES,
                similarity_score, cluster_prob, key_mode, tempo, and id columns.
        playlist_track_ids: Set of track IDs that belong to the playlist (positives).
        scaler: Fitted MinMaxScaler (used to copy into the pipeline).

    Returns:
        Tuple of (fitted_pipeline, metrics_dict).
        metrics_dict keys: accuracy, precision, recall, f1, roc_auc, precision_at_10.
    """
    # Derive labels
    ids = (
        corpus["id"].to_list()
        if "id" in corpus.columns
        else [str(i) for i in range(len(corpus))]
    )
    y_full = np.array(
        [1 if track_id in playlist_track_ids else 0 for track_id in ids], dtype=np.int32
    )

    # Subsample negatives to keep training tractable on large corpora
    pos_idx = np.where(y_full == 1)[0]
    neg_idx = np.where(y_full == 0)[0]
    if len(neg_idx) > max_negatives:
        rng = np.random.default_rng(42)
        neg_idx = rng.choice(neg_idx, size=max_negatives, replace=False)
    keep_idx = np.sort(np.concatenate([pos_idx, neg_idx]))
    corpus = corpus[keep_idx.tolist()]
    y = y_full[keep_idx]

    # Build a dummy playlist_profile for feature extraction
    # For training, camelot_distance and tempo_deviation are computed against a neutral profile
    # The scaler copy in the pipeline normalises these at predict time
    modal_key = ""
    mean_tempo = 0.0
    if "tempo" in corpus.columns:
        pos_mask = np.array(
            [1 if tid in playlist_track_ids else 0 for tid in ids], dtype=bool
        )
        if pos_mask.any():
            mean_tempo = float(corpus["tempo"].to_numpy()[pos_mask].mean())
        # modal_key: most common key_mode among positives
        if "key_mode" in corpus.columns and pos_mask.any():
            pos_key_modes = corpus.filter(pl.Series(pos_mask))["key_mode"].to_list()
            modal_key = max(set(pos_key_modes), key=pos_key_modes.count)

    playlist_profile = {"modal_key": modal_key, "mean_tempo": mean_tempo}

    # Ensure required retrieval columns exist (use zeros if absent — training fallback)
    candidates = corpus
    if "similarity_score" not in corpus.columns:
        candidates = candidates.with_columns(pl.lit(0.0).alias("similarity_score"))
    if "cluster_prob" not in corpus.columns:
        candidates = candidates.with_columns(pl.lit(0.0).alias("cluster_prob"))

    X = build_rerank_features(candidates, playlist_profile)

    # Train/test split 70/30
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.30, random_state=42, stratify=y if y.sum() > 1 else None
    )

    lgbm = LGBMClassifier(
        class_weight="balanced",
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=31,
        random_state=42,
        verbose=-1,
    )
    calibrated = CalibratedClassifierCV(lgbm, cv=2, method="isotonic")

    pipeline = Pipeline(
        [
            ("scaler_copy", MinMaxScaler()),
            ("classifier", calibrated),
        ]
    )
    pipeline.fit(X_train, y_train)

    # Evaluate on test set
    y_pred = pipeline.predict(X_test)
    y_proba = pipeline.predict_proba(X_test)[:, 1]

    accuracy = float(accuracy_score(y_test, y_pred))
    precision = float(precision_score(y_test, y_pred, zero_division=0))
    recall = float(recall_score(y_test, y_pred, zero_division=0))
    f1 = float(f1_score(y_test, y_pred, zero_division=0))

    # roc_auc requires at least one positive in test set
    if len(np.unique(y_test)) > 1:
        roc_auc = float(roc_auc_score(y_test, y_proba))
    else:
        roc_auc = float("nan")

    # precision@10: fraction of top-10 (by predicted proba) that are true positives
    top10_idx = np.argsort(y_proba)[::-1][:10]
    precision_at_10 = float(y_test[top10_idx].sum() / min(10, len(y_test)))

    metrics: dict = {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "roc_auc": roc_auc,
        "precision_at_10": precision_at_10,
    }

    return pipeline, metrics


def rerank_candidates(
    candidates: pl.DataFrame,
    classifier: Pipeline,
    playlist_profile: dict,
) -> pl.DataFrame:
    """Score candidates via classifier predict_proba, add rerank_score, sort descending.

    Args:
        candidates: DataFrame with CLASSIFIER_FEATURES columns (pre-computed retrieval signals).
        classifier: Fitted sklearn Pipeline with predict_proba.
        playlist_profile: Dict with keys: modal_key, mean_tempo (for feature computation).

    Returns:
        candidates DataFrame with 'rerank_score' column added, sorted descending by score.
    """
    X = build_rerank_features(candidates, playlist_profile)
    proba = classifier.predict_proba(X)[:, 1]
    result = candidates.with_columns(pl.Series("rerank_score", proba))
    return result.sort("rerank_score", descending=True)


def load_classifier(playlist_slug: str, models_dir: Path) -> Pipeline | None:
    """Load a serialised classifier pkl if it exists, None otherwise.

    Args:
        playlist_slug: Playlist identifier slug (e.g. "zoukini", "lady_stardust").
        models_dir: Directory containing classifier pkl files.

    Returns:
        Fitted Pipeline or None if no pkl is found.
    """
    path = models_dir / f"classifier_{playlist_slug}.pkl"
    if not path.exists():
        return None
    return joblib.load(path)


def save_classifier(classifier: Pipeline, playlist_slug: str, models_dir: Path) -> Path:
    """Serialise a fitted classifier Pipeline to models/classifier_{slug}.pkl.

    Args:
        classifier: Fitted sklearn Pipeline to save.
        playlist_slug: Playlist identifier slug.
        models_dir: Directory to write the pkl file into.

    Returns:
        Path to the written pkl file.
    """
    models_dir.mkdir(parents=True, exist_ok=True)
    path = models_dir / f"classifier_{playlist_slug}.pkl"
    joblib.dump(classifier, path)
    return path
