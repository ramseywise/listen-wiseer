"""Training script: reads DuckDB (or archived CSVs), trains all models, writes pkls to models/.

Run from repo root:
    PYTHONPATH=src uv run python -m recommend.train
    PYTHONPATH=src uv run python -m recommend.train --compare   # LightGBM vs CatBoost
"""

from __future__ import annotations

import argparse
import gc
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import joblib
import numpy as np
import polars as pl
from sklearn.metrics import silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import MinMaxScaler

from etl.db import get_connection, init_schema
from paths import ARCHIVED_DIR, CACHE_DIR, MODELS_DIR, REPO_ROOT
from recommend.modules.classifiers import (
    ModelType,
    save_classifier,
    train_playlist_classifier,
)
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


# ---------------------------------------------------------------------------
# Metrics persistence
# ---------------------------------------------------------------------------


class MetricsWriter:
    """Collects per-playlist metrics and writes them to a JSONL file.

    Each line is a JSON object with: timestamp, mode, model_type, playlist, metrics.
    A final summary line is appended on close.

    File naming: ``{mode}_{model_type}_{YYYYMMDD_HHMMSS}.jsonl``
    """

    def __init__(self, mode: str, model_type: str, metrics_dir: Path) -> None:
        self._mode = mode
        self._model_type = model_type
        self._timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        self._rows: list[dict] = []

        metrics_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{mode}_{model_type}_{self._timestamp}.jsonl"
        self._path = metrics_dir / filename

    @property
    def path(self) -> str:
        """Return path relative to REPO_ROOT, or absolute if outside the repo."""
        try:
            return str(self._path.relative_to(REPO_ROOT))
        except ValueError:
            return str(self._path)

    def add(self, playlist: str, model_type: str, metrics: dict) -> None:
        """Record one playlist's metrics."""
        row = {
            "timestamp": self._timestamp,
            "mode": self._mode,
            "model_type": model_type,
            "playlist": playlist,
            "metrics": {k: round(v, 4) for k, v in metrics.items()},
        }
        self._rows.append(row)

    def write(self, summary: dict | None = None) -> None:
        """Flush all rows + optional summary to disk."""
        with open(self._path, "w") as fh:
            for row in self._rows:
                fh.write(json.dumps(row) + "\n")
            if summary:
                fh.write(
                    json.dumps(
                        {
                            "timestamp": self._timestamp,
                            "mode": self._mode,
                            "model_type": self._model_type,
                            "summary": summary,
                        }
                    )
                    + "\n"
                )
        log.info("train.metrics.saved", path=self.path, n_rows=len(self._rows))


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


def _log_classifier_metrics(
    playlist_name: str,
    metrics: dict,
    model_type: ModelType,
) -> None:
    """Log classifier training metrics via structlog."""
    log.info(
        "train.classifier.done",
        playlist=playlist_name,
        model_type=model_type,
        accuracy=round(metrics["accuracy"], 3),
        precision=round(metrics["precision"], 3),
        recall=round(metrics["recall"], 3),
        f1=round(metrics["f1"], 3),
        roc_auc=round(metrics["roc_auc"], 3),
        precision_at_10=round(metrics["precision_at_10"], 3),
        brier_score=round(metrics["brier_score"], 4),
        log_loss=round(metrics["log_loss"], 4),
    )


def train_classifiers(
    corpus: pl.DataFrame,
    enoa: pl.DataFrame,
    scaler: MinMaxScaler,
    gmm: GaussianMixture,
    gmm_scaler: MinMaxScaler,
    model_type: ModelType = "lightgbm",
) -> tuple[int, int]:
    """Train one classifier per playlist in enoa.csv.

    Args:
        corpus: Full training corpus DataFrame.
        enoa: ENOA DataFrame with playlist_name and id columns.
        scaler: Fitted MinMaxScaler from GMM step (legacy, passed through).
        gmm: Fitted GaussianMixture model for computing cluster_prob.
        gmm_scaler: Fitted MinMaxScaler for the GMM feature space.
        model_type: Which estimator to train ("lightgbm" or "catboost").

    Returns:
        Tuple of (n_trained, n_skipped).
    """
    corpus_ids: set[str] = set(corpus["id"].cast(pl.Utf8).to_list())
    playlist_names = enoa["playlist_name"].unique().sort().to_list()

    log.info("train.classifiers.start", n_playlists=len(playlist_names), model_type=model_type)

    writer = MetricsWriter(mode="train", model_type=model_type, metrics_dir=MODELS_DIR / "metrics")
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
            model_type=model_type,
            n_pos=n_pos,
            n_neg=n_neg,
        )

        pipeline, metrics = train_playlist_classifier(
            corpus=corpus,
            playlist_track_ids=playlist_track_ids,
            scaler=scaler,
            gmm=gmm,
            gmm_scaler=gmm_scaler,
            model_type=model_type,
        )

        _log_classifier_metrics(playlist_name, metrics, model_type)
        writer.add(playlist_name, model_type, metrics)

        saved_path = save_classifier(pipeline, slug, MODELS_DIR)
        log.debug("train.classifier.saved", path=str(saved_path.relative_to(REPO_ROOT)))

        del pipeline
        gc.collect()
        n_trained += 1

    writer.write(summary={"n_trained": n_trained, "n_skipped": n_skipped})
    return n_trained, n_skipped


def compare_models(
    corpus: pl.DataFrame,
    enoa: pl.DataFrame,
    scaler: MinMaxScaler,
    gmm: GaussianMixture,
    gmm_scaler: MinMaxScaler,
) -> None:
    """Train both LightGBM and CatBoost for each playlist, log side-by-side metrics.

    This is informational only — models are NOT saved. Use for benchmarking.

    Args:
        corpus: Full training corpus DataFrame.
        enoa: ENOA DataFrame with playlist_name and id columns.
        scaler: Fitted MinMaxScaler from GMM step.
        gmm: Fitted GaussianMixture model.
        gmm_scaler: Fitted MinMaxScaler for the GMM feature space.
    """
    corpus_ids: set[str] = set(corpus["id"].cast(pl.Utf8).to_list())
    playlist_names = enoa["playlist_name"].unique().sort().to_list()

    log.info("train.compare.start", n_playlists=len(playlist_names))

    writer = MetricsWriter(
        mode="compare", model_type="lgbm_vs_catboost", metrics_dir=MODELS_DIR / "metrics"
    )
    all_metrics: dict[str, list[dict]] = {"lightgbm": [], "catboost": []}
    lgbm_wins = 0
    cat_wins = 0
    ties = 0

    for playlist_name in playlist_names:
        raw_ids = (
            enoa.filter(pl.col("playlist_name") == playlist_name)["id"].cast(pl.Utf8).to_list()
        )
        playlist_track_ids: set[str] = {tid for tid in raw_ids if tid in corpus_ids}
        n_pos = len(playlist_track_ids)

        if n_pos < MIN_POSITIVES:
            continue

        log.info("train.compare.playlist", playlist=playlist_name, n_pos=n_pos)

        results: dict[str, dict] = {}
        for model_type in ("lightgbm", "catboost"):
            _, metrics = train_playlist_classifier(
                corpus=corpus,
                playlist_track_ids=playlist_track_ids,
                scaler=scaler,
                gmm=gmm,
                gmm_scaler=gmm_scaler,
                model_type=model_type,  # type: ignore[arg-type]
            )
            results[model_type] = metrics
            all_metrics[model_type].append(metrics)
            _log_classifier_metrics(playlist_name, metrics, model_type)  # type: ignore[arg-type]
            writer.add(playlist_name, model_type, metrics)

        # Compare on brier_score (lower is better)
        lgbm_brier = results["lightgbm"]["brier_score"]
        cat_brier = results["catboost"]["brier_score"]
        lgbm_ll = results["lightgbm"]["log_loss"]
        cat_ll = results["catboost"]["log_loss"]

        log.info(
            "train.compare.result",
            playlist=playlist_name,
            lgbm_brier=round(lgbm_brier, 4),
            cat_brier=round(cat_brier, 4),
            lgbm_logloss=round(lgbm_ll, 4),
            cat_logloss=round(cat_ll, 4),
            brier_winner="catboost" if cat_brier < lgbm_brier else "lightgbm",
            logloss_winner="catboost" if cat_ll < lgbm_ll else "lightgbm",
        )

        if cat_brier < lgbm_brier:
            cat_wins += 1
        elif lgbm_brier < cat_brier:
            lgbm_wins += 1
        else:
            ties += 1

        gc.collect()

    # Aggregate summary
    n_compared = lgbm_wins + cat_wins + ties
    summary: dict = {"n_playlists": n_compared}
    if n_compared > 0:
        mean_lgbm_brier = np.mean([m["brier_score"] for m in all_metrics["lightgbm"]])
        mean_cat_brier = np.mean([m["brier_score"] for m in all_metrics["catboost"]])
        mean_lgbm_ll = np.mean([m["log_loss"] for m in all_metrics["lightgbm"]])
        mean_cat_ll = np.mean([m["log_loss"] for m in all_metrics["catboost"]])

        summary.update(
            {
                "lgbm_wins_brier": lgbm_wins,
                "catboost_wins_brier": cat_wins,
                "ties_brier": ties,
                "mean_lgbm_brier": round(float(mean_lgbm_brier), 4),
                "mean_catboost_brier": round(float(mean_cat_brier), 4),
                "mean_lgbm_logloss": round(float(mean_lgbm_ll), 4),
                "mean_catboost_logloss": round(float(mean_cat_ll), 4),
            }
        )

        log.info(
            "train.compare.summary",
            **summary,
        )
    else:
        log.warning("train.compare.no_playlists", msg="No playlists met MIN_POSITIVES threshold")

    writer.write(summary=summary)


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Train recommendation models (GMM + per-playlist classifiers).",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Train both LightGBM and CatBoost, log comparison metrics (no models saved).",
    )
    parser.add_argument(
        "--model-type",
        choices=["lightgbm", "catboost"],
        default="lightgbm",
        help="Estimator to use for training (default: lightgbm).",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for the training script."""
    configure_logging()
    np.random.seed(42)

    args = _parse_args()

    log.info("train.start", compare=args.compare, model_type=args.model_type)

    corpus, enoa = load_data()

    # Cache preprocessed corpus for engine.py
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    corpus_cache_path = CACHE_DIR / "corpus_features.parquet"
    corpus.write_parquet(corpus_cache_path)
    log.info("train.corpus.cached", path=str(corpus_cache_path.relative_to(REPO_ROOT)))

    gmm, gmm_scaler, _corpus_features = train_gmm(corpus)

    CLASSIFIER_CORPUS_LIMIT = 20_000
    if len(corpus) > CLASSIFIER_CORPUS_LIMIT:
        corpus = corpus.sample(n=CLASSIFIER_CORPUS_LIMIT, seed=42)
        log.info("train.corpus.subsampled", n=CLASSIFIER_CORPUS_LIMIT)
    gc.collect()

    if args.compare:
        compare_models(corpus, enoa, gmm_scaler, gmm, gmm_scaler)
    else:
        n_trained, n_skipped = train_classifiers(
            corpus,
            enoa,
            gmm_scaler,
            gmm,
            gmm_scaler,
            model_type=args.model_type,
        )

        log.info(
            "train.done",
            n_trained=n_trained,
            n_skipped=n_skipped,
            min_positives=MIN_POSITIVES,
            models_dir=str(MODELS_DIR),
            model_type=args.model_type,
        )


if __name__ == "__main__":
    main()
