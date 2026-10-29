"""RecommendationEngine — single entry point for all recommendation pipelines.

Owns artifact loading (corpus, genre_map, GMM, scaler). Routes requests by
request_type to the appropriate pipeline. Classifiers are loaded lazily and
cached per playlist slug.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import duckdb
import joblib
import numpy as np
import polars as pl
from sklearn.mixture import GaussianMixture
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler

from recommend.modules.classifiers import load_classifier
from recommend.modules.genre import load_genre_map_from_db
from recommend.modules.similarity import SIMILARITY_FEATURES
from recommend.pipelines import (
    ArtistPipeline,
    GenrePipeline,
    PlaylistPipeline,
    TrackPipeline,
)
from recommend.schemas import RecommendRequest, RecommendResult
from utils.logging import get_logger

log = get_logger(__name__)


class RecommendationEngine:
    """Single entry point for track, artist, playlist, and genre recommendations.

    Loads corpus and model artifacts at init. Routes recommend() calls to the
    correct pipeline based on request_type. Per-playlist classifiers are loaded
    lazily from models_dir.

    Args:
        models_dir: Directory containing gmm_corpus.pkl, scaler_corpus.pkl,
            and per-playlist classifier_{slug}.pkl files.
        data_dir: Root data directory. Corpus loaded from
            data_dir/cache/corpus_features.parquet (written by train.py).
            Genre map loaded from DuckDB genre_xy table.
        playlist_tracks_fn: Maps a playlist ID to its track IDs (playlist pipeline
            only). Injected so the engine never holds a DB connection per request.
    """

    def __init__(
        self,
        models_dir: Path,
        data_dir: Path,
        playlist_tracks_fn: Callable[[str], list[str]] | None = None,
    ) -> None:
        # Load corpus from Parquet cache (written by train.py)
        self._corpus: pl.DataFrame = self._load_corpus(data_dir)

        # Load genre map from DuckDB
        self._genre_map: pl.DataFrame = self._load_genre_map()

        # Load GMM
        gmm_path = models_dir / "gmm_corpus.pkl"
        if not gmm_path.exists():
            raise FileNotFoundError(
                f"GMM model not found: {gmm_path}. "
                "Run `uv run python -m recommend.train` to generate it."
            )
        self._gmm: GaussianMixture = joblib.load(gmm_path)

        # Load scaler
        scaler_path = models_dir / "scaler_corpus.pkl"
        if not scaler_path.exists():
            raise FileNotFoundError(
                f"Scaler not found: {scaler_path}. "
                "Run `uv run python -m recommend.train` to generate it."
            )
        self._scaler: MinMaxScaler = joblib.load(scaler_path)

        self._models_dir: Path = models_dir
        self._classifier_cache: dict[str, Pipeline | None] = {}
        self._playlist_tracks_fn = playlist_tracks_fn

    @staticmethod
    def _load_corpus(data_dir: Path) -> pl.DataFrame:
        """Load corpus from Parquet cache written by train.py.

        Args:
            data_dir: Root data directory.

        Returns:
            Corpus DataFrame.

        Raises:
            FileNotFoundError: If Parquet cache doesn't exist.
        """
        parquet_path = data_dir / "cache" / "corpus_features.parquet"
        if not parquet_path.exists():
            raise FileNotFoundError(
                f"Corpus not found at {parquet_path}. "
                "Run `PYTHONPATH=src uv run python -m recommend.train` first."
            )
        corpus = pl.read_parquet(parquet_path)
        log.info("engine.corpus.loaded", source="parquet", n_rows=len(corpus))
        return corpus

    @staticmethod
    def _load_genre_map() -> pl.DataFrame:
        """Load genre map from the DuckDB genre_xy table.

        Returns:
            Genre map DataFrame with [first_genre, top, left] columns.

        Raises:
            FileNotFoundError: If DB is not accessible or genre_xy is empty.
        """
        from paths import DB_PATH

        conn = duckdb.connect(str(DB_PATH), read_only=True)
        genre_df = load_genre_map_from_db(conn)
        conn.close()
        if genre_df.is_empty():
            raise FileNotFoundError(
                f"genre_xy table is empty in {DB_PATH}. Run bootstrap to populate it."
            )
        log.info("engine.genre_map.loaded", source="duckdb", n_rows=len(genre_df))
        return genre_df

    def recommend(self, request: RecommendRequest) -> RecommendResult:
        """Route the request to the correct pipeline and return a RecommendResult.

        Soft failures (unknown seed, missing Spotify client, fetch errors) return
        a RecommendResult with track_uris=[] and a populated explanation rather
        than raising.

        Args:
            request: Recommendation parameters (type, seed_id, target_playlist_id, k).

        Returns:
            RecommendResult with tracks, scores, and explanation.
        """
        classifier: Pipeline | None = None
        if request.target_playlist_id:
            classifier = self._load_classifier(request.target_playlist_id)

        if request.request_type == "track":
            return self._run_track(request, classifier)
        elif request.request_type == "artist":
            return self._run_artist(request, classifier)
        elif request.request_type == "playlist":
            return self._run_playlist(request, classifier)
        else:
            # genre
            return self._run_genre(request, classifier)

    # ------------------------------------------------------------------
    # Pipeline runners
    # ------------------------------------------------------------------

    def _run_track(
        self,
        request: RecommendRequest,
        classifier: Pipeline | None,
    ) -> RecommendResult:
        query = self._resolve_track_features(request.seed_id)
        if query is None:
            return RecommendResult(
                track_uris=[],
                track_ids=[],
                track_names=[],
                scores=[],
                pipeline_used="track",
                explanation=(
                    f"Track '{request.seed_id}' was not found in the corpus. "
                    "Only tracks already in the training data can be used as seeds."
                ),
            )
        return TrackPipeline().run(
            request=request,
            query_features=query,
            corpus=self._corpus,
            gmm=self._gmm,
            scaler=self._scaler,
            classifier=classifier,
        )

    def _run_artist(
        self,
        request: RecommendRequest,
        classifier: Pipeline | None,
    ) -> RecommendResult:
        artist_tracks = self._resolve_artist_tracks(request.seed_id)
        return ArtistPipeline().run(
            request=request,
            artist_track_features=artist_tracks,
            corpus=self._corpus,
            gmm=self._gmm,
            scaler=self._scaler,
            classifier=classifier,
        )

    def _run_playlist(
        self,
        request: RecommendRequest,
        classifier: Pipeline | None,
    ) -> RecommendResult:
        track_ids = self._playlist_tracks_fn(request.seed_id) if self._playlist_tracks_fn else []
        playlist_tracks_df = self._corpus.filter(pl.col("id").is_in(track_ids))
        if playlist_tracks_df.is_empty():
            return RecommendResult(
                track_uris=[],
                track_ids=[],
                track_names=[],
                scores=[],
                pipeline_used="playlist",
                explanation=(
                    f"Playlist '{request.seed_id}' has no tracks in the corpus "
                    "(unknown playlist, or its tracks have no audio features)."
                ),
            )

        return PlaylistPipeline().run(
            request=request,
            playlist_tracks=playlist_tracks_df,
            corpus=self._corpus,
            gmm=self._gmm,
            scaler=self._scaler,
            classifier=classifier,
        )

    def _run_genre(
        self,
        request: RecommendRequest,
        classifier: Pipeline | None,
    ) -> RecommendResult:
        return GenrePipeline().run(
            request=request,
            genre_map=self._genre_map,
            corpus=self._corpus,
            gmm=self._gmm,
            scaler=self._scaler,
            classifier=classifier,
        )

    # ------------------------------------------------------------------
    # Lazy classifier loading
    # ------------------------------------------------------------------

    def _load_classifier(self, playlist_id: str) -> Pipeline | None:
        """Lazily load a per-playlist classifier from disk and cache it.

        Uses playlist_id directly as the slug. In practice the agent passes
        a slug (e.g. "zoukini") as target_playlist_id.

        Args:
            playlist_id: Playlist slug used as the pkl filename key.

        Returns:
            Fitted Pipeline or None if no pkl exists.
        """
        if playlist_id in self._classifier_cache:
            return self._classifier_cache[playlist_id]

        clf = load_classifier(playlist_id, self._models_dir)
        self._classifier_cache[playlist_id] = clf
        return clf

    # ------------------------------------------------------------------
    # Feature resolution helpers
    # ------------------------------------------------------------------

    def _resolve_track_features(self, track_id: str) -> np.ndarray | None:
        """Look up a track in the corpus by ID and return its SIMILARITY_FEATURES vector.

        Args:
            track_id: Spotify track ID.

        Returns:
            1-D np.ndarray of shape (12,) aligned to SIMILARITY_FEATURES, or None if
            the track is not in the corpus.
        """
        match = self._corpus.filter(pl.col("id") == track_id)
        if len(match) == 0:
            return None
        available = [c for c in SIMILARITY_FEATURES if c in match.columns]
        row_values = match.select(available).to_numpy()[0].astype(np.float64)
        # If some SIMILARITY_FEATURES columns are absent, pad with zeros
        if len(available) == len(SIMILARITY_FEATURES):
            return row_values
        full = np.zeros(len(SIMILARITY_FEATURES), dtype=np.float64)
        for i, feat in enumerate(SIMILARITY_FEATURES):
            if feat in available:
                full[i] = row_values[available.index(feat)]
        return full

    def _resolve_artist_tracks(self, artist_id: str) -> pl.DataFrame:
        """Filter the corpus to tracks by a given artist ID (substring match on artist_ids).

        Args:
            artist_id: Spotify artist ID to search for.

        Returns:
            Subset of corpus rows where artist_ids contains artist_id.
            Empty DataFrame if none found.
        """
        if "artist_ids" not in self._corpus.columns:
            return self._corpus.clear()
        return self._corpus.filter(pl.col("artist_ids").str.contains(artist_id))
