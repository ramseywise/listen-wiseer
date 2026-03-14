"""Unit tests for src/recommend/engine.py — RecommendationEngine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import polars as pl
import pytest

from recommend.engine import RecommendationEngine
from recommend.schemas import RecommendRequest, RecommendResult

# ---------------------------------------------------------------------------
# Helpers: check whether real models exist
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parents[4]  # listen-wiseer/
_MODELS_DIR = _REPO_ROOT / "models"
_DATA_DIR = _REPO_ROOT / "data"

_MODELS_AVAILABLE = (
    (_MODELS_DIR / "gmm_corpus.pkl").exists()
    and (_MODELS_DIR / "scaler_corpus.pkl").exists()
    and (_DATA_DIR / "archived" / "spotify_train_data.csv").exists()
    and (_DATA_DIR / "archived" / "genres" / "genre_xy.csv").exists()
)


# ---------------------------------------------------------------------------
# Test 1 — Init with missing pkl raises FileNotFoundError with path in message
# ---------------------------------------------------------------------------


def test_init_missing_gmm_raises_file_not_found(tmp_path: Path) -> None:
    """Engine init should raise FileNotFoundError when gmm_corpus.pkl is missing.

    The error message must include the expected pkl path so the user knows
    exactly which file is missing.
    """
    # Provide real data files if available so we only trigger the pkl check,
    # otherwise we need at least a valid CSV. We use tmp_path for models_dir
    # which has no pkl files at all.
    if not (_DATA_DIR / "archived" / "spotify_train_data.csv").exists():
        pytest.skip("Training data not available — skip pkl-missing test")

    with pytest.raises(FileNotFoundError) as exc_info:
        RecommendationEngine(
            models_dir=tmp_path,  # tmp_path has no pkl files
            data_dir=_DATA_DIR,
        )

    error_message = str(exc_info.value)
    # Path should appear in the message
    assert "gmm_corpus.pkl" in error_message


def test_init_missing_scaler_raises_file_not_found(tmp_path: Path) -> None:
    """Engine init should raise FileNotFoundError when scaler_corpus.pkl is missing.

    Creates a dummy gmm_corpus.pkl so the GMM check passes but scaler check fails.
    """
    if not (_DATA_DIR / "archived" / "spotify_train_data.csv").exists():
        pytest.skip("Training data not available — skip pkl-missing test")

    import joblib
    from sklearn.mixture import GaussianMixture

    # Place a dummy gmm pkl so only the scaler check fires
    dummy_gmm = GaussianMixture(n_components=2, random_state=42)
    joblib.dump(dummy_gmm, tmp_path / "gmm_corpus.pkl")
    # scaler_corpus.pkl intentionally absent

    with pytest.raises(FileNotFoundError) as exc_info:
        RecommendationEngine(
            models_dir=tmp_path,
            data_dir=_DATA_DIR,
        )

    error_message = str(exc_info.value)
    assert "scaler_corpus.pkl" in error_message


# ---------------------------------------------------------------------------
# Test 2 — recommend with unknown track_id returns [] + non-empty explanation
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODELS_AVAILABLE, reason="Real models not yet trained")
def test_recommend_unknown_track_id_returns_empty_with_explanation() -> None:
    """recommend() with a track_id not in corpus returns graceful empty result."""
    engine = RecommendationEngine(
        models_dir=_MODELS_DIR,
        data_dir=_DATA_DIR,
    )
    request = RecommendRequest(
        request_type="track",
        seed_id="NONEXISTENT_TRACK_ID_XYZ",
        k=5,
    )
    result = engine.recommend(request)

    assert isinstance(result, RecommendResult)
    assert result.track_uris == []
    assert result.track_ids == []
    assert len(result.explanation) > 0


# ---------------------------------------------------------------------------
# Test 3 — routing: correct pipeline called for each request_type
# These tests mock the pipeline classes so no real pkl loading is needed.
# ---------------------------------------------------------------------------


def _make_mock_engine(tmp_path: Path) -> tuple[RecommendationEngine, Path]:
    """Create a RecommendationEngine with all heavy dependencies patched.

    Returns the engine and the models_dir used.
    """
    import joblib
    from sklearn.mixture import GaussianMixture
    from sklearn.preprocessing import MinMaxScaler

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    data_dir = tmp_path / "data"
    (data_dir / "archived" / "genres").mkdir(parents=True)

    # Minimal corpus CSV
    _KEY_MODES = [
        "C Minor", "G Minor", "D Minor", "A Minor", "E Minor", "F Minor",
        "Bb Minor", "Eb Minor", "Ab Minor", "Db Minor", "F# Minor", "B Minor",
        "C Major", "G Major", "D Major", "A Major", "E Major", "F Major",
        "Bb Major", "Eb Major", "Ab Major", "Db Major", "F# Major", "B Major",
    ]
    _DECADES = ["1960s", "1970s", "1980s", "1990s", "2000s", "2010s", "2020s", "1950s"]

    rng = np.random.default_rng(42)
    n = 30
    corpus = pl.DataFrame({
        "id": [f"track_{i:03d}" for i in range(n)],
        "track_name": [f"Track {i}" for i in range(n)],
        "danceability": rng.uniform(0.0, 1.0, n).tolist(),
        "energy": rng.uniform(0.0, 1.0, n).tolist(),
        "loudness": rng.uniform(-60.0, 0.0, n).tolist(),
        "speechiness": rng.uniform(0.0, 1.0, n).tolist(),
        "acousticness": rng.uniform(0.0, 1.0, n).tolist(),
        "instrumentalness": rng.uniform(0.0, 1.0, n).tolist(),
        "liveness": rng.uniform(0.0, 1.0, n).tolist(),
        "valence": rng.uniform(0.0, 1.0, n).tolist(),
        "tempo": rng.uniform(60.0, 200.0, n).tolist(),
        "popularity": rng.integers(0, 100, n).tolist(),
        "top": rng.uniform(0.0, 5000.0, n).tolist(),
        "left": rng.uniform(0.0, 5000.0, n).tolist(),
        "key_mode": [_KEY_MODES[i % len(_KEY_MODES)] for i in range(n)],
        "decade": [_DECADES[i % len(_DECADES)] for i in range(n)],
        "artist_ids": [f"artist_{i % 5}" for i in range(n)],
        "first_genre": ["zouk"] * n,
    })
    corpus.write_csv(data_dir / "archived" / "spotify_train_data.csv")

    # Minimal genre_xy CSV
    genre_df = pl.DataFrame({
        "first_genre": ["zouk", "bossa nova"],
        "color": ["#ff0000", "#00ff00"],
        "top": [1000.0, 2000.0],
        "left": [1000.0, 2000.0],
    })
    genre_df.write_csv(data_dir / "archived" / "genres" / "genre_xy.csv")

    # Fit minimal GMM + scaler and save pkls
    from recommend.modules.clustering import fit_gmm as _fit_gmm
    gmm, scaler = _fit_gmm(corpus, n_components=2, random_state=42)
    joblib.dump(gmm, models_dir / "gmm_corpus.pkl")
    joblib.dump(scaler, models_dir / "scaler_corpus.pkl")

    engine = RecommendationEngine(
        models_dir=models_dir,
        data_dir=data_dir,
    )
    return engine, models_dir


def test_recommend_routes_to_track_pipeline(tmp_path: Path) -> None:
    """recommend(request_type='track') calls TrackPipeline.run()."""
    engine, _ = _make_mock_engine(tmp_path)

    fake_result = RecommendResult(
        track_uris=["spotify:track:abc"],
        track_ids=["abc"],
        track_names=["Test Track"],
        scores=[0.9],
        pipeline_used="track",
        explanation="test",
    )

    with patch("recommend.engine.TrackPipeline") as MockPipeline:
        mock_instance = MockPipeline.return_value
        mock_instance.run.return_value = fake_result

        request = RecommendRequest(request_type="track", seed_id="track_000", k=3)
        result = engine.recommend(request)

    mock_instance.run.assert_called_once()
    assert result.pipeline_used == "track"


def test_recommend_routes_to_artist_pipeline(tmp_path: Path) -> None:
    """recommend(request_type='artist') calls ArtistPipeline.run()."""
    engine, _ = _make_mock_engine(tmp_path)

    fake_result = RecommendResult(
        track_uris=[],
        track_ids=[],
        track_names=[],
        scores=[],
        pipeline_used="artist",
        explanation="test artist",
    )

    with patch("recommend.engine.ArtistPipeline") as MockPipeline:
        mock_instance = MockPipeline.return_value
        mock_instance.run.return_value = fake_result

        request = RecommendRequest(request_type="artist", seed_id="artist_0", k=3)
        result = engine.recommend(request)

    mock_instance.run.assert_called_once()
    assert result.pipeline_used == "artist"


def test_recommend_routes_to_genre_pipeline(tmp_path: Path) -> None:
    """recommend(request_type='genre') calls GenrePipeline.run()."""
    engine, _ = _make_mock_engine(tmp_path)

    fake_result = RecommendResult(
        track_uris=[],
        track_ids=[],
        track_names=[],
        scores=[],
        pipeline_used="genre",
        explanation="test genre",
    )

    with patch("recommend.engine.GenrePipeline") as MockPipeline:
        mock_instance = MockPipeline.return_value
        mock_instance.run.return_value = fake_result

        request = RecommendRequest(request_type="genre", seed_id="zouk", k=3)
        result = engine.recommend(request)

    mock_instance.run.assert_called_once()
    assert result.pipeline_used == "genre"


def test_recommend_playlist_without_spotify_client_returns_graceful(tmp_path: Path) -> None:
    """recommend(request_type='playlist') with no spotify_client returns empty result."""
    engine, _ = _make_mock_engine(tmp_path)
    # Engine was created without spotify_client

    request = RecommendRequest(request_type="playlist", seed_id="some_playlist_id", k=3)
    result = engine.recommend(request)

    assert isinstance(result, RecommendResult)
    assert result.track_uris == []
    assert "Spotify client not configured" in result.explanation


# ---------------------------------------------------------------------------
# Test 4 — _resolve_track_features and _resolve_artist_tracks internals
# ---------------------------------------------------------------------------


def test_resolve_track_features_returns_none_for_missing_id(tmp_path: Path) -> None:
    """_resolve_track_features returns None when track_id is not in corpus."""
    engine, _ = _make_mock_engine(tmp_path)
    result = engine._resolve_track_features("DOES_NOT_EXIST")
    assert result is None


def test_resolve_track_features_returns_ndarray_for_known_id(tmp_path: Path) -> None:
    """_resolve_track_features returns a 1-D numpy array for a known track ID."""
    engine, _ = _make_mock_engine(tmp_path)
    result = engine._resolve_track_features("track_000")
    assert result is not None
    assert isinstance(result, np.ndarray)
    assert result.ndim == 1
    assert len(result) == 12  # len(SIMILARITY_FEATURES)


def test_resolve_artist_tracks_returns_empty_for_missing_artist(tmp_path: Path) -> None:
    """_resolve_artist_tracks returns an empty DataFrame for an unknown artist."""
    engine, _ = _make_mock_engine(tmp_path)
    result = engine._resolve_artist_tracks("UNKNOWN_ARTIST_XYZ")
    assert isinstance(result, pl.DataFrame)
    assert len(result) == 0


def test_resolve_artist_tracks_returns_rows_for_known_artist(tmp_path: Path) -> None:
    """_resolve_artist_tracks returns matching rows for a known artist substring."""
    engine, _ = _make_mock_engine(tmp_path)
    result = engine._resolve_artist_tracks("artist_0")
    assert isinstance(result, pl.DataFrame)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Test 5 — classifier cache
# ---------------------------------------------------------------------------


def test_load_classifier_returns_none_for_nonexistent_slug(tmp_path: Path) -> None:
    """_load_classifier returns None and caches it when no pkl exists."""
    engine, _ = _make_mock_engine(tmp_path)
    result = engine._load_classifier("nonexistent_playlist")
    assert result is None
    # Second call should hit cache
    result2 = engine._load_classifier("nonexistent_playlist")
    assert result2 is None
    assert "nonexistent_playlist" in engine._classifier_cache
