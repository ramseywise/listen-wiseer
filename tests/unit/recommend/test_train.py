"""Unit tests for src/recommend/train.py — synthetic fixtures, no API, no real data files."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import polars as pl
import pytest
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import MinMaxScaler

from recommend.modules.classifiers import ALL_GEN4
from recommend.modules.clustering import fit_gmm
from recommend.train import (
    MIN_POSITIVES,
    _load_corpus,
    _playlist_slug,
    compare_models,
    load_data,
    train_classifiers,
    train_gmm,
)
from utils.const import all_decades, all_key_modes

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_corpus(n: int = 60, seed: int = 42) -> pl.DataFrame:
    """Synthetic corpus with all columns required by clustering + classifier training."""
    rng = np.random.default_rng(seed)
    key_modes = rng.choice(all_key_modes, size=n).tolist()
    decades = rng.choice(all_decades, size=n).tolist()
    gen4s = rng.choice(ALL_GEN4, size=n).tolist()
    return pl.DataFrame(
        {
            "id": [f"track_{i:04d}" for i in range(n)],
            # CLUSTER_AUDIO_FEATURES
            "danceability": rng.uniform(0.0, 1.0, n).tolist(),
            "energy": rng.uniform(0.0, 1.0, n).tolist(),
            "loudness": rng.uniform(-60.0, 0.0, n).tolist(),
            "speechiness": rng.uniform(0.0, 0.5, n).tolist(),
            "acousticness": rng.uniform(0.0, 1.0, n).tolist(),
            "instrumentalness": rng.uniform(0.0, 1.0, n).tolist(),
            "liveness": rng.uniform(0.0, 1.0, n).tolist(),
            "valence": rng.uniform(0.0, 1.0, n).tolist(),
            "tempo": rng.uniform(60.0, 200.0, n).tolist(),
            "top": rng.uniform(0.0, 5000.0, n).tolist(),
            "left": rng.uniform(0.0, 5000.0, n).tolist(),
            # Extra columns used by classifiers
            "popularity": rng.integers(0, 100, n).tolist(),
            # Categorical
            "key_mode": key_modes,
            "decade": decades,
            "gen_4": gen4s,
            # Engineered features (Phase 3a)
            "fave_score": rng.uniform(0.0, 5.0, n).tolist(),
            "n_playlists": rng.integers(0, 5, n).astype(float).tolist(),
            "year_normalized": rng.uniform(0.0, 1.0, n).tolist(),
            "duration_ms_normalized": rng.uniform(0.0, 1.0, n).tolist(),
            "embedding_similarity": rng.uniform(0.0, 1.0, n).tolist(),
            "playlist_diversity": rng.integers(0, 4, n).astype(float).tolist(),
        }
    )


def _make_enoa(corpus: pl.DataFrame, playlist_name: str, n_pos: int) -> pl.DataFrame:
    """Build a minimal enoa DataFrame with n_pos tracks from corpus assigned to playlist_name."""
    pos_ids = corpus["id"].head(n_pos).to_list()
    return pl.DataFrame({"playlist_name": [playlist_name] * n_pos, "id": pos_ids})


@pytest.fixture
def corpus() -> pl.DataFrame:
    return _make_corpus(n=60)


@pytest.fixture
def gmm_and_scaler(corpus: pl.DataFrame) -> tuple[GaussianMixture, MinMaxScaler]:
    return fit_gmm(corpus, n_components=4, random_state=42)


# ---------------------------------------------------------------------------
# _playlist_slug
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Zoukini", "zoukini"),
        ("Lady Stardust", "lady_stardust"),
        ("¡Zapatos! ¡Zapatos!", "zapatos_zapatos"),
        ("Already_snake", "already_snake"),
        ("  spaces  ", "__spaces__"),
    ],
)
def test_playlist_slug(name: str, expected: str) -> None:
    assert _playlist_slug(name) == expected


# ---------------------------------------------------------------------------
# load_data
# ---------------------------------------------------------------------------


def test_load_data_missing_corpus_raises(tmp_path: Path) -> None:
    missing = tmp_path / "no_corpus.csv"
    enoa = tmp_path / "enoa.csv"
    enoa.write_text("playlist_name,id\ntest,t1\n")
    with (
        patch("recommend.train.get_connection", side_effect=FileNotFoundError("no db")),
        patch("recommend.train.CORPUS_CSV", missing),
        patch("recommend.train.ENOA_CSV", enoa),
    ):
        with pytest.raises(FileNotFoundError, match="No data source available"):
            load_data()


def test_load_data_missing_enoa_raises(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.csv"
    corpus.write_text("id,danceability\nt1,0.5\n")
    missing = tmp_path / "no_enoa.csv"
    with (
        patch("recommend.train.get_connection", side_effect=FileNotFoundError("no db")),
        patch("recommend.train.CORPUS_CSV", corpus),
        patch("recommend.train.ENOA_CSV", missing),
    ):
        with pytest.raises(FileNotFoundError, match="ENOA CSV not found"):
            load_data()


def test_load_data_success(tmp_path: Path) -> None:
    corpus_path = tmp_path / "corpus.csv"
    enoa_path = tmp_path / "enoa.csv"
    corpus_path.write_text("id,danceability\nt1,0.5\nt2,0.7\n")
    enoa_path.write_text("playlist_name,id\ntest,t1\n")
    with (
        patch("recommend.train.get_connection", side_effect=FileNotFoundError("no db")),
        patch("recommend.train.CORPUS_CSV", corpus_path),
        patch("recommend.train.ENOA_CSV", enoa_path),
    ):
        corpus_df, enoa_df = load_data()
    assert len(corpus_df) == 2
    assert len(enoa_df) == 1


# ---------------------------------------------------------------------------
# train_gmm
# ---------------------------------------------------------------------------


def test_train_gmm_writes_pkls(corpus: pl.DataFrame, tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    with (
        patch("recommend.train.MODELS_DIR", models_dir),
        patch("recommend.train.REPO_ROOT", tmp_path),
    ):
        gmm, scaler, features = train_gmm(corpus)

    assert (models_dir / "gmm_corpus.pkl").exists()
    assert (models_dir / "scaler_corpus.pkl").exists()
    assert features.shape[0] == len(corpus)


def test_train_gmm_returns_fitted_objects(corpus: pl.DataFrame, tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    with (
        patch("recommend.train.MODELS_DIR", models_dir),
        patch("recommend.train.REPO_ROOT", tmp_path),
    ):
        gmm, scaler, _ = train_gmm(corpus)

    assert isinstance(gmm, GaussianMixture)
    assert isinstance(scaler, MinMaxScaler)
    assert gmm.n_components == 8


# ---------------------------------------------------------------------------
# train_classifiers — now requires gmm + gmm_scaler
# ---------------------------------------------------------------------------


def test_train_classifiers_skips_when_too_few_positives(
    corpus: pl.DataFrame,
    gmm_and_scaler: tuple,
    tmp_path: Path,
) -> None:
    enoa = _make_enoa(corpus, "tiny_playlist", n_pos=MIN_POSITIVES - 1)
    gmm, gmm_scaler = gmm_and_scaler
    scaler = MinMaxScaler()
    models_dir = tmp_path / "models"
    with (
        patch("recommend.train.MODELS_DIR", models_dir),
        patch("recommend.train.REPO_ROOT", tmp_path),
    ):
        n_trained, n_skipped = train_classifiers(
            corpus,
            enoa,
            scaler,
            gmm=gmm,
            gmm_scaler=gmm_scaler,
        )

    assert n_trained == 0
    assert n_skipped == 1
    assert not list(models_dir.glob("classifier_*.pkl"))


def test_train_classifiers_trains_when_enough_positives(
    corpus: pl.DataFrame,
    gmm_and_scaler: tuple,
    tmp_path: Path,
) -> None:
    enoa = _make_enoa(corpus, "good_playlist", n_pos=MIN_POSITIVES + 5)
    gmm, gmm_scaler = gmm_and_scaler
    scaler = MinMaxScaler()
    models_dir = tmp_path / "models"
    with (
        patch("recommend.train.MODELS_DIR", models_dir),
        patch("recommend.train.REPO_ROOT", tmp_path),
    ):
        n_trained, n_skipped = train_classifiers(
            corpus,
            enoa,
            scaler,
            gmm=gmm,
            gmm_scaler=gmm_scaler,
        )

    assert n_trained == 1
    assert n_skipped == 0
    assert (models_dir / "classifier_good_playlist.pkl").exists()


def test_train_classifiers_mixed(
    corpus: pl.DataFrame,
    gmm_and_scaler: tuple,
    tmp_path: Path,
) -> None:
    enoa = pl.concat(
        [
            _make_enoa(corpus, "big_playlist", n_pos=MIN_POSITIVES + 5),
            _make_enoa(corpus, "small_playlist", n_pos=MIN_POSITIVES - 1),
        ]
    )
    gmm, gmm_scaler = gmm_and_scaler
    scaler = MinMaxScaler()
    models_dir = tmp_path / "models"
    with (
        patch("recommend.train.MODELS_DIR", models_dir),
        patch("recommend.train.REPO_ROOT", tmp_path),
    ):
        n_trained, n_skipped = train_classifiers(
            corpus,
            enoa,
            scaler,
            gmm=gmm,
            gmm_scaler=gmm_scaler,
        )

    assert n_trained == 1
    assert n_skipped == 1


@pytest.mark.parametrize("model_type", ["lightgbm", "catboost"])
def test_train_classifiers_model_type(
    corpus: pl.DataFrame,
    gmm_and_scaler: tuple,
    tmp_path: Path,
    model_type: str,
) -> None:
    """Both model types produce a valid classifier pkl."""
    enoa = _make_enoa(corpus, "test_playlist", n_pos=MIN_POSITIVES + 5)
    gmm, gmm_scaler = gmm_and_scaler
    scaler = MinMaxScaler()
    models_dir = tmp_path / "models"
    with (
        patch("recommend.train.MODELS_DIR", models_dir),
        patch("recommend.train.REPO_ROOT", tmp_path),
    ):
        n_trained, _ = train_classifiers(
            corpus,
            enoa,
            scaler,
            gmm=gmm,
            gmm_scaler=gmm_scaler,
            model_type=model_type,  # type: ignore[arg-type]
        )

    assert n_trained == 1
    assert (models_dir / "classifier_test_playlist.pkl").exists()


# ---------------------------------------------------------------------------
# compare_models
# ---------------------------------------------------------------------------


def test_compare_models_runs(
    corpus: pl.DataFrame,
    gmm_and_scaler: tuple,
) -> None:
    """compare_models completes without error on synthetic data."""
    enoa = _make_enoa(corpus, "cmp_playlist", n_pos=MIN_POSITIVES + 5)
    gmm, gmm_scaler = gmm_and_scaler
    scaler = MinMaxScaler()
    # compare_models doesn't save anything, so no need to patch MODELS_DIR
    compare_models(corpus, enoa, scaler, gmm=gmm, gmm_scaler=gmm_scaler)


def test_compare_models_skips_small_playlists(
    corpus: pl.DataFrame,
    gmm_and_scaler: tuple,
) -> None:
    """compare_models skips playlists below MIN_POSITIVES without error."""
    enoa = _make_enoa(corpus, "tiny_playlist", n_pos=MIN_POSITIVES - 1)
    gmm, gmm_scaler = gmm_and_scaler
    scaler = MinMaxScaler()
    # Should complete without error (logs warning about no playlists)
    compare_models(corpus, enoa, scaler, gmm=gmm, gmm_scaler=gmm_scaler)


# ---------------------------------------------------------------------------
# _load_corpus dual-mode
# ---------------------------------------------------------------------------


def test_load_corpus_falls_back_to_csv(tmp_path: Path) -> None:
    """_load_corpus falls back to CSV when DB is unavailable."""
    csv_path = tmp_path / "corpus.csv"
    csv_path.write_text("id,danceability\nt1,0.5\nt2,0.7\n")

    with (
        patch("recommend.train.get_connection", side_effect=FileNotFoundError("no db")),
        patch("recommend.train.CORPUS_CSV", csv_path),
    ):
        corpus = _load_corpus()
    assert len(corpus) == 2


def test_load_corpus_raises_when_no_source(tmp_path: Path) -> None:
    """_load_corpus raises FileNotFoundError when both sources are unavailable."""
    missing = tmp_path / "missing.csv"
    with (
        patch("recommend.train.get_connection", side_effect=FileNotFoundError("no db")),
        patch("recommend.train.CORPUS_CSV", missing),
    ):
        with pytest.raises(FileNotFoundError, match="No data source available"):
            _load_corpus()
