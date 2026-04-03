"""Unit tests for src/recommend/train.py — synthetic fixtures, no API, no real data files."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import polars as pl
import pytest

from recommend.train import (
    MIN_POSITIVES,
    _playlist_slug,
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
        }
    )


def _make_enoa(corpus: pl.DataFrame, playlist_name: str, n_pos: int) -> pl.DataFrame:
    """Build a minimal enoa DataFrame with n_pos tracks from corpus assigned to playlist_name."""
    pos_ids = corpus["id"].head(n_pos).to_list()
    return pl.DataFrame({"playlist_name": [playlist_name] * n_pos, "id": pos_ids})


@pytest.fixture
def corpus() -> pl.DataFrame:
    return _make_corpus(n=60)


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
    with patch("recommend.train.CORPUS_CSV", missing), patch(
        "recommend.train.ENOA_CSV", enoa
    ):
        with pytest.raises(FileNotFoundError, match="Corpus CSV not found"):
            load_data()


def test_load_data_missing_enoa_raises(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.csv"
    corpus.write_text("id,danceability\nt1,0.5\n")
    missing = tmp_path / "no_enoa.csv"
    with patch("recommend.train.CORPUS_CSV", corpus), patch(
        "recommend.train.ENOA_CSV", missing
    ):
        with pytest.raises(FileNotFoundError, match="ENOA CSV not found"):
            load_data()


def test_load_data_success(tmp_path: Path) -> None:
    corpus_path = tmp_path / "corpus.csv"
    enoa_path = tmp_path / "enoa.csv"
    corpus_path.write_text("id,danceability\nt1,0.5\nt2,0.7\n")
    enoa_path.write_text("playlist_name,id\ntest,t1\n")
    with patch("recommend.train.CORPUS_CSV", corpus_path), patch(
        "recommend.train.ENOA_CSV", enoa_path
    ):
        corpus_df, enoa_df = load_data()
    assert len(corpus_df) == 2
    assert len(enoa_df) == 1


# ---------------------------------------------------------------------------
# train_gmm
# ---------------------------------------------------------------------------


def test_train_gmm_writes_pkls(corpus: pl.DataFrame, tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    with patch("recommend.train.MODELS_DIR", models_dir), patch(
        "recommend.train._REPO_ROOT", tmp_path
    ):
        gmm, scaler, features = train_gmm(corpus)

    assert (models_dir / "gmm_corpus.pkl").exists()
    assert (models_dir / "scaler_corpus.pkl").exists()
    assert features.shape[0] == len(corpus)


def test_train_gmm_returns_fitted_objects(corpus: pl.DataFrame, tmp_path: Path) -> None:
    from sklearn.mixture import GaussianMixture
    from sklearn.preprocessing import MinMaxScaler

    models_dir = tmp_path / "models"
    with patch("recommend.train.MODELS_DIR", models_dir), patch(
        "recommend.train._REPO_ROOT", tmp_path
    ):
        gmm, scaler, _ = train_gmm(corpus)

    assert isinstance(gmm, GaussianMixture)
    assert isinstance(scaler, MinMaxScaler)
    assert gmm.n_components == 8


# ---------------------------------------------------------------------------
# train_classifiers
# ---------------------------------------------------------------------------


def test_train_classifiers_skips_when_too_few_positives(
    corpus: pl.DataFrame, tmp_path: Path
) -> None:
    enoa = _make_enoa(corpus, "tiny_playlist", n_pos=MIN_POSITIVES - 1)
    from sklearn.preprocessing import MinMaxScaler

    scaler = MinMaxScaler()
    models_dir = tmp_path / "models"
    with patch("recommend.train.MODELS_DIR", models_dir), patch(
        "recommend.train._REPO_ROOT", tmp_path
    ):
        n_trained, n_skipped = train_classifiers(corpus, enoa, scaler)

    assert n_trained == 0
    assert n_skipped == 1
    assert not list(models_dir.glob("classifier_*.pkl"))


def test_train_classifiers_trains_when_enough_positives(
    corpus: pl.DataFrame, tmp_path: Path
) -> None:
    enoa = _make_enoa(corpus, "good_playlist", n_pos=MIN_POSITIVES + 5)
    from sklearn.preprocessing import MinMaxScaler

    scaler = MinMaxScaler()
    models_dir = tmp_path / "models"
    with patch("recommend.train.MODELS_DIR", models_dir), patch(
        "recommend.train._REPO_ROOT", tmp_path
    ):
        n_trained, n_skipped = train_classifiers(corpus, enoa, scaler)

    assert n_trained == 1
    assert n_skipped == 0
    assert (models_dir / "classifier_good_playlist.pkl").exists()


def test_train_classifiers_mixed(corpus: pl.DataFrame, tmp_path: Path) -> None:
    enoa = pl.concat(
        [
            _make_enoa(corpus, "big_playlist", n_pos=MIN_POSITIVES + 5),
            _make_enoa(corpus, "small_playlist", n_pos=MIN_POSITIVES - 1),
        ]
    )
    from sklearn.preprocessing import MinMaxScaler

    scaler = MinMaxScaler()
    models_dir = tmp_path / "models"
    with patch("recommend.train.MODELS_DIR", models_dir), patch(
        "recommend.train._REPO_ROOT", tmp_path
    ):
        n_trained, n_skipped = train_classifiers(corpus, enoa, scaler)

    assert n_trained == 1
    assert n_skipped == 1
