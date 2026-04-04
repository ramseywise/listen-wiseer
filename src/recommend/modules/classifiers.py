"""Binary reranker: LightGBM or CatBoost, one model per playlist. Calibrated probabilities."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import joblib
import numpy as np
import polars as pl
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.mixture import GaussianMixture
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler

from recommend.modules.clustering import build_cluster_features, predict_cluster_probs
from recommend.modules.similarity import (
    SIMILARITY_FEATURES,
    camelot_distance,
    compute_weighted_cosine,
    playlist_centroid,
)
from utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Feature constants
# ---------------------------------------------------------------------------

CLASSIFIER_FEATURES: list[str] = SIMILARITY_FEATURES + [
    "similarity_score",
    "cluster_prob",
    "camelot_distance",
    "tempo_deviation",
    # Engineered features (Phase 3a)
    "embedding_similarity",
    "playlist_diversity",
]

CATEGORICAL_FEATURES: list[str] = ["decade", "gen_4"]

# Known categories for one-hot encoding (LightGBM path)
ALL_DECADES: list[str] = [
    "1950s",
    "1960s",
    "1970s",
    "1980s",
    "1990s",
    "2000s",
    "2010s",
    "2020s",
]
ALL_GEN4: list[str] = ["acoustic", "dance", "electronic", "instrumental"]

_REQUIRED_RETRIEVAL_COLS = {"similarity_score", "cluster_prob"}

ModelType = Literal["lightgbm", "catboost"]


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


def _one_hot_column(values: list[str], categories: list[str]) -> np.ndarray:
    """One-hot encode a list of string values against a fixed category list.

    Returns:
        np.ndarray of shape (len(values), len(categories)).
    """
    cat_index = {cat: idx for idx, cat in enumerate(categories)}
    ohe = np.zeros((len(values), len(categories)), dtype=np.float64)
    for row_idx, val in enumerate(values):
        if val in cat_index:
            ohe[row_idx, cat_index[val]] = 1.0
    return ohe


def _create_estimator(
    model_type: ModelType,
    cat_feature_indices: list[int] | None = None,
) -> object:
    """Factory: create the base estimator for the given model type.

    Args:
        model_type: Which estimator to create.
        cat_feature_indices: For CatBoost, column indices of categorical features.
            Must be passed at construction time (sklearn clone requires all params
            in the constructor).

    Returns an unfitted estimator (LGBMClassifier or CatBoostClassifier).
    """
    if model_type == "lightgbm":
        return LGBMClassifier(
            class_weight="balanced",
            n_estimators=200,
            learning_rate=0.05,
            num_leaves=31,
            random_state=42,
            verbose=-1,
        )
    elif model_type == "catboost":
        from catboost import CatBoostClassifier

        return CatBoostClassifier(
            auto_class_weights="Balanced",
            iterations=200,
            learning_rate=0.05,
            depth=6,
            random_seed=42,
            verbose=0,
            cat_features=cat_feature_indices or [],
        )
    else:
        raise ValueError(f"Unknown model_type: {model_type!r}")


def build_rerank_features(
    candidates: pl.DataFrame,
    playlist_profile: dict,
    model_type: ModelType = "lightgbm",
) -> np.ndarray:
    """Build feature matrix for the reranker from a candidates DataFrame.

    Computes camelot_distance and tempo_deviation per-row using values from
    playlist_profile. Expects similarity_score and cluster_prob already present
    as columns on candidates.

    For model_type="lightgbm", categorical features (decade, gen_4) are one-hot
    encoded. For model_type="catboost", they are excluded from the numeric matrix
    (CatBoost handles them natively via cat_features indices).

    Args:
        candidates: DataFrame with SIMILARITY_FEATURES + similarity_score + cluster_prob.
        playlist_profile: Dict with keys: centroid, modal_key, mean_tempo.
        model_type: Which estimator will consume the features.

    Returns:
        np.ndarray of shape (n_candidates, n_features).

    Raises:
        ValueError: If similarity_score or cluster_prob columns are missing.
    """
    missing = _REQUIRED_RETRIEVAL_COLS - set(candidates.columns)
    if missing:
        raise ValueError(f"candidates DataFrame is missing required columns: {sorted(missing)}")

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

    similarity_score = candidates["similarity_score"].to_numpy().astype(np.float64).reshape(-1, 1)
    cluster_prob = candidates["cluster_prob"].to_numpy().astype(np.float64).reshape(-1, 1)

    # Engineered features: embedding_similarity and playlist_diversity
    embedding_sim = (
        candidates["embedding_similarity"].to_numpy().astype(np.float64).reshape(-1, 1)
        if "embedding_similarity" in candidates.columns
        else np.zeros((len(candidates), 1), dtype=np.float64)
    )
    playlist_div = (
        candidates["playlist_diversity"].to_numpy().astype(np.float64).reshape(-1, 1)
        if "playlist_diversity" in candidates.columns
        else np.zeros((len(candidates), 1), dtype=np.float64)
    )

    parts = [
        base_arr,
        similarity_score,
        cluster_prob,
        camelot_dists.reshape(-1, 1),
        tempo_devs.reshape(-1, 1),
        embedding_sim,
        playlist_div,
    ]

    # Categorical features — one-hot for LightGBM, skip for CatBoost
    if model_type == "lightgbm":
        decade_vals = (
            candidates["decade"].cast(pl.Utf8).fill_null("").to_list()
            if "decade" in candidates.columns
            else [""] * len(candidates)
        )
        gen4_vals = (
            candidates["gen_4"].cast(pl.Utf8).fill_null("").to_list()
            if "gen_4" in candidates.columns
            else [""] * len(candidates)
        )
        parts.append(_one_hot_column(decade_vals, ALL_DECADES))
        parts.append(_one_hot_column(gen4_vals, ALL_GEN4))

    X = np.concatenate(parts, axis=1)
    return X


def _extract_categorical_features(candidates: pl.DataFrame) -> np.ndarray:
    """Extract categorical features as integer codes for CatBoost.

    Returns:
        np.ndarray of shape (n_candidates, len(CATEGORICAL_FEATURES)), dtype object (strings).
    """
    cols = []
    for col_name in CATEGORICAL_FEATURES:
        if col_name in candidates.columns:
            vals = candidates[col_name].cast(pl.Utf8).fill_null("_unknown_").to_list()
        else:
            vals = ["_unknown_"] * len(candidates)
        cols.append(vals)
    return np.column_stack(cols)


def _compute_cluster_probs_for_corpus(
    corpus: pl.DataFrame,
    gmm: GaussianMixture,
    gmm_scaler: MinMaxScaler,
) -> np.ndarray:
    """Compute max cluster probability for each corpus row.

    Mirrors the signal produced by filter_corpus_by_cluster at inference time.

    Returns:
        1-d array of shape (n_corpus,) with max cluster membership probability per row.
    """
    corpus_features, _ = build_cluster_features(corpus, gmm_scaler, fit_scaler=False)
    probs = predict_cluster_probs(corpus_features, gmm)
    return probs.max(axis=1)


def _compute_similarity_scores_for_corpus(
    corpus: pl.DataFrame,
    playlist_track_ids: set[str],
) -> np.ndarray:
    """Compute cosine similarity of each corpus row to the playlist centroid.

    Uses the same SIMILARITY_FEATURES and compute_weighted_cosine as the
    inference path (find_similar). Standard cosine — no leave-one-out.

    Returns:
        1-d array of shape (n_corpus,) with similarity scores in [0, 1].
    """
    ids = corpus["id"].to_list() if "id" in corpus.columns else []
    pos_mask = pl.Series([tid in playlist_track_ids for tid in ids])
    positives_df = corpus.filter(pos_mask)

    if positives_df.is_empty():
        return np.zeros(len(corpus), dtype=np.float64)

    centroid = playlist_centroid(positives_df, SIMILARITY_FEATURES)
    corpus_features = corpus.select(SIMILARITY_FEATURES).to_numpy().astype(np.float64)
    weights = np.ones(len(SIMILARITY_FEATURES), dtype=np.float64)
    return compute_weighted_cosine(corpus_features, centroid, weights)


def train_playlist_classifier(
    corpus: pl.DataFrame,
    playlist_track_ids: set[str],
    scaler: MinMaxScaler,
    gmm: GaussianMixture | None = None,
    gmm_scaler: MinMaxScaler | None = None,
    model_type: ModelType = "lightgbm",
    max_negatives: int = 5000,
) -> tuple[Pipeline, dict]:
    """Train a binary classifier for a single playlist.

    Derives binary y_target from playlist_track_ids membership.
    Wraps the estimator in CalibratedClassifierCV (isotonic, cv=2).

    When gmm and gmm_scaler are provided, computes real cluster_prob values
    instead of zeros. Similarly, computes similarity_score from the playlist
    centroid to close the train/inference feature gap.

    Args:
        corpus: Full training corpus; must contain all SIMILARITY_FEATURES,
                key_mode, tempo, and id columns.
        playlist_track_ids: Set of track IDs that belong to the playlist (positives).
        scaler: Fitted MinMaxScaler (unused legacy param, kept for backward compat).
        gmm: Fitted GaussianMixture for computing cluster_prob at train time.
        gmm_scaler: Fitted MinMaxScaler for the GMM feature space.
        model_type: Which estimator to use ("lightgbm" or "catboost").
        max_negatives: Maximum number of negative samples to keep.

    Returns:
        Tuple of (fitted_pipeline, metrics_dict).
        metrics_dict keys: accuracy, precision, recall, f1, roc_auc, precision_at_10,
                           brier_score, log_loss.
    """
    # --- Compute retrieval features BEFORE subsampling ---
    # similarity_score: cosine similarity to playlist centroid
    sim_scores = _compute_similarity_scores_for_corpus(corpus, playlist_track_ids)
    corpus = corpus.with_columns(pl.Series("similarity_score", sim_scores))

    # cluster_prob: max GMM cluster membership probability
    if gmm is not None and gmm_scaler is not None:
        cluster_probs = _compute_cluster_probs_for_corpus(corpus, gmm, gmm_scaler)
        corpus = corpus.with_columns(pl.Series("cluster_prob", cluster_probs))
    elif "cluster_prob" not in corpus.columns:
        log.warning("train.classifier.no_gmm", msg="GMM not provided; cluster_prob set to 0.0")
        corpus = corpus.with_columns(pl.lit(0.0).alias("cluster_prob"))

    # --- Derive labels ---
    ids = corpus["id"].to_list() if "id" in corpus.columns else [str(i) for i in range(len(corpus))]
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

    # --- Build playlist profile for camelot_distance / tempo_deviation ---
    modal_key = ""
    mean_tempo = 0.0
    if "tempo" in corpus.columns:
        # Recompute pos_mask on the subsampled corpus
        sub_ids = corpus["id"].to_list() if "id" in corpus.columns else []
        pos_mask = np.array([1 if tid in playlist_track_ids else 0 for tid in sub_ids], dtype=bool)
        if pos_mask.any():
            mean_tempo = float(corpus["tempo"].to_numpy()[pos_mask].mean())
        if "key_mode" in corpus.columns and pos_mask.any():
            pos_key_modes = corpus.filter(pl.Series(pos_mask))["key_mode"].to_list()
            modal_key = max(set(pos_key_modes), key=pos_key_modes.count)

    playlist_profile = {"modal_key": modal_key, "mean_tempo": mean_tempo}

    # --- Build feature matrix ---
    X = build_rerank_features(corpus, playlist_profile, model_type=model_type)

    # For CatBoost, also extract categorical columns
    cat_data = None
    if model_type == "catboost":
        cat_data = _extract_categorical_features(corpus)

    # --- Train/test split 70/30 ---
    if cat_data is not None:
        X_train, X_test, y_train, y_test, cat_train, cat_test = train_test_split(
            X,
            y,
            cat_data,
            test_size=0.30,
            random_state=42,
            stratify=y if y.sum() > 1 else None,
        )
        # Combine numeric and categorical for CatBoost
        X_train = np.column_stack([X_train, cat_train])
        X_test = np.column_stack([X_test, cat_test])
    else:
        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=0.30,
            random_state=42,
            stratify=y if y.sum() > 1 else None,
        )

    # --- Create and fit pipeline ---
    if model_type == "catboost":
        # CatBoost needs cat_features indices at construction time.
        # They're the last len(CATEGORICAL_FEATURES) columns after numeric features.
        n_numeric = X.shape[1]
        cat_feature_indices = list(range(n_numeric, n_numeric + len(CATEGORICAL_FEATURES)))
        base_estimator = _create_estimator(model_type, cat_feature_indices=cat_feature_indices)
        # CatBoost's predict_proba is well-calibrated out of the box.
        # CalibratedClassifierCV uses sklearn.clone() which is incompatible with
        # CatBoost's cat_features param, so we skip calibration wrapping.
        pipeline = Pipeline(
            [
                ("classifier", base_estimator),
            ]
        )
    else:
        base_estimator = _create_estimator(model_type)
        calibrated = CalibratedClassifierCV(base_estimator, cv=2, method="isotonic")
        pipeline = Pipeline(
            [
                ("scaler_copy", MinMaxScaler()),
                ("classifier", calibrated),
            ]
        )

    pipeline.fit(X_train, y_train)

    # --- Evaluate on test set ---
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

    # Calibration metrics — critical for rerank score quality
    brier = float(brier_score_loss(y_test, y_proba))
    logloss = float(log_loss(y_test, y_proba))

    metrics: dict = {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "roc_auc": roc_auc,
        "precision_at_10": precision_at_10,
        "brier_score": brier,
        "log_loss": logloss,
    }

    return pipeline, metrics


def rerank_candidates(
    candidates: pl.DataFrame,
    classifier: Pipeline,
    playlist_profile: dict,
    model_type: ModelType = "lightgbm",
) -> pl.DataFrame:
    """Score candidates via classifier predict_proba, add rerank_score, sort descending.

    Args:
        candidates: DataFrame with CLASSIFIER_FEATURES columns (pre-computed retrieval signals).
        classifier: Fitted sklearn Pipeline with predict_proba.
        playlist_profile: Dict with keys: modal_key, mean_tempo (for feature computation).
        model_type: Which estimator was used to train the classifier.

    Returns:
        candidates DataFrame with 'rerank_score' column added, sorted descending by score.
    """
    X = build_rerank_features(candidates, playlist_profile, model_type=model_type)

    if model_type == "catboost":
        cat_data = _extract_categorical_features(candidates)
        X = np.column_stack([X, cat_data])

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
