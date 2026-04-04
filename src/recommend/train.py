"""Training script: reads DuckDB (or archived CSVs), trains all models, writes pkls to models/.

Run from repo root:
    PYTHONPATH=src uv run python -m recommend.train
"""

from __future__ import annotations

import gc
import re

import duckdb
import joblib
import numpy as np
import polars as pl
from sklearn.metrics import silhouette_score

from etl.db import get_connection, init_schema
from paths import ARCHIVED_DIR, CACHE_DIR, MODELS_DIR, REPO_ROOT
from recommend.modules.classifiers import save_classifier, train_playlist_classifier
from recommend.modules.clustering import (
    build_cluster_features,
    fit_gmm,
    predict_cluster_probs,
)
from recommend.preprocessing import build_feature_matrix
from utils.logging import configure_logging, get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CORPUS_CSV = ARCHIVED_DIR / "spotify_train_data.csv"
ENOA_CSV = ARCHIVED_DIR / "enoa.csv"

MIN_POSITIVES = 20


def _playlist_slug(name: str) -> str:
    """Convert a playlist name to a safe file slug.

    Lowercases, replaces spaces with underscores, strips any character that
    is not alphanumeric or underscore.

    Examples:
        "Zoukini"            -> "zoukini"
        "Lady Stardust"      -> "lady_stardust"
        "¡Zapatos! ¡Zapatos!" -> "zapatos_zapatos"
    """
    slug = name.lower().replace(" ", "_")
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    return slug


def _load_corpus() -> pl.DataFrame:
    """Load corpus: DuckDB first, CSV fallback."""
    try:
        conn = get_connection(read_only=False)
        init_schema(conn)  # refresh track_profile view (idempotent)
        corpus = build_feature_matrix(conn)
        conn.close()
        if corpus.is_empty():
            raise ValueError("DuckDB corpus is empty")
        log.info("train.corpus.source", source="duckdb", n_rows=len(corpus))
        return corpus
    except (duckdb.IOException, FileNotFoundError, ValueError) as exc:
        log.info("train.corpus.db_fallback", reason=str(exc))

    if not CORPUS_CSV.exists():
        raise FileNotFoundError(
            f"No data source available. DuckDB not usable and CSV not found at {CORPUS_CSV}"
        )
    corpus = pl.read_csv(CORPUS_CSV, null_values=["", "NA", "NaN"])
    log.info("train.corpus.source", source="csv", n_rows=len(corpus))
    return corpus


def _load_enoa() -> pl.DataFrame:
    """Load ENOA playlist membership from CSV."""
    if not ENOA_CSV.exists():
        raise FileNotFoundError(f"ENOA CSV not found: {ENOA_CSV}")
    return pl.read_csv(ENOA_CSV, null_values=["", "NA", "NaN"])


def load_data() -> tuple[pl.DataFrame, pl.DataFrame]:
    """Load corpus and enoa DataFrames.

    Tries DuckDB first (build_feature_matrix), falls back to archived CSVs.
    ENOA always loaded from CSV (no DB table yet).

    Returns:
        Tuple of (corpus, enoa) as Polars DataFrames.

    Raises:
        FileNotFoundError: If neither DB nor CSV sources are available.
    """
    corpus = _load_corpus()
    enoa = _load_enoa()

    log.info(
        "train.data.loaded",
        corpus_rows=len(corpus),
        corpus_cols=len(corpus.columns),
        enoa_rows=len(enoa),
    )
    return corpus, enoa


def train_gmm(corpus: pl.DataFrame) -> tuple:
    """Fit GMM + scaler on corpus, save pkls, return (gmm, scaler, corpus_features_scaled).

    Args:
        corpus: Full training corpus DataFrame.

    Returns:
        Tuple of (gmm, scaler, corpus_features_scaled).
    """
    log.info("train.gmm.start", n_rows=len(corpus))

    gmm, scaler = fit_gmm(corpus, n_components=8, random_state=42)

    corpus_features, _ = build_cluster_features(corpus, scaler, fit_scaler=False)
    cluster_probs = predict_cluster_probs(corpus_features, gmm)
    cluster_ids = np.argmax(cluster_probs, axis=1)

    sil = silhouette_score(corpus_features, cluster_ids, random_state=42)
    cluster_counts = np.bincount(cluster_ids, minlength=8)

    log.info(
        "train.gmm.fit",
        n_components=8,
        silhouette=round(float(sil), 4),
        cluster_counts=cluster_counts.tolist(),
    )

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    gmm_path = MODELS_DIR / "gmm_corpus.pkl"
    scaler_path = MODELS_DIR / "scaler_corpus.pkl"
    joblib.dump(gmm, gmm_path)
    joblib.dump(scaler, scaler_path)

    log.info(
        "train.gmm.saved",
        gmm=str(gmm_path.relative_to(REPO_ROOT)),
        scaler=str(scaler_path.relative_to(REPO_ROOT)),
    )

    return gmm, scaler, corpus_features


def train_classifiers(
    corpus: pl.DataFrame,
    enoa: pl.DataFrame,
    scaler,
) -> tuple[int, int]:
    """Train one LightGBM classifier per playlist in enoa.csv.

    Args:
        corpus: Full training corpus DataFrame.
        enoa: ENOA DataFrame with playlist_name and id columns.
        scaler: Fitted MinMaxScaler from GMM step.

    Returns:
        Tuple of (n_trained, n_skipped).
    """
    corpus_ids: set[str] = set(corpus["id"].cast(pl.Utf8).to_list())
    playlist_names = enoa["playlist_name"].unique().sort().to_list()

    log.info("train.classifiers.start", n_playlists=len(playlist_names))

    n_trained = 0
    n_skipped = 0

    for playlist_name in playlist_names:
        slug = _playlist_slug(playlist_name)

        raw_ids = (
            enoa.filter(pl.col("playlist_name") == playlist_name)["id"].cast(pl.Utf8).to_list()
        )
        playlist_track_ids: set[str] = {tid for tid in raw_ids if tid in corpus_ids}
        n_pos = len(playlist_track_ids)

        if n_pos < MIN_POSITIVES:
            log.info(
                "train.classifier.skip",
                playlist=playlist_name,
                n_pos=n_pos,
                min_required=MIN_POSITIVES,
            )
            n_skipped += 1
            continue

        n_neg = len(corpus) - n_pos
        log.info(
            "train.classifier.training",
            playlist=playlist_name,
            n_pos=n_pos,
            n_neg=n_neg,
        )

        pipeline, metrics = train_playlist_classifier(
            corpus=corpus,
            playlist_track_ids=playlist_track_ids,
            scaler=scaler,
        )

        log.info(
            "train.classifier.done",
            playlist=playlist_name,
            accuracy=round(metrics["accuracy"], 3),
            precision=round(metrics["precision"], 3),
            recall=round(metrics["recall"], 3),
            f1=round(metrics["f1"], 3),
            roc_auc=round(metrics["roc_auc"], 3),
            precision_at_10=round(metrics["precision_at_10"], 3),
        )

        saved_path = save_classifier(pipeline, slug, MODELS_DIR)
        log.debug("train.classifier.saved", path=str(saved_path.relative_to(REPO_ROOT)))

        del pipeline
        gc.collect()
        n_trained += 1

    return n_trained, n_skipped


def main() -> None:
    """Entry point for the training script."""
    configure_logging()
    np.random.seed(42)

    log.info("train.start")

    corpus, enoa = load_data()

    # Cache preprocessed corpus for engine.py
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    corpus_cache_path = CACHE_DIR / "corpus_features.parquet"
    corpus.write_parquet(corpus_cache_path)
    log.info("train.corpus.cached", path=str(corpus_cache_path.relative_to(REPO_ROOT)))

    gmm, scaler, _corpus_features = train_gmm(corpus)

    CLASSIFIER_CORPUS_LIMIT = 20_000
    if len(corpus) > CLASSIFIER_CORPUS_LIMIT:
        corpus = corpus.sample(n=CLASSIFIER_CORPUS_LIMIT, seed=42)
        log.info("train.corpus.subsampled", n=CLASSIFIER_CORPUS_LIMIT)
    gc.collect()

    n_trained, n_skipped = train_classifiers(corpus, enoa, scaler)

    log.info(
        "train.done",
        n_trained=n_trained,
        n_skipped=n_skipped,
        min_positives=MIN_POSITIVES,
        models_dir=str(MODELS_DIR),
    )


if __name__ == "__main__":
    main()
