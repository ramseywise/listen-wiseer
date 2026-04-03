"""RecommendationEngine — single entry point for all recommendation pipelines.

Owns artifact loading (corpus, genre_map, GMM, scaler). Routes requests by
request_type to the appropriate pipeline. Classifiers are loaded lazily and
cached per playlist slug.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import polars as pl
from sklearn.mixture import GaussianMixture
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler

from recommend.modules.classifiers import load_classifier
from recommend.modules.genre import load_genre_map
from recommend.modules.similarity import SIMILARITY_FEATURES
from recommend.pipelines import (
    ArtistPipeline,
    GenrePipeline,
    PlaylistPipeline,
    TrackPipeline,
)
from recommend.schemas import RecommendRequest, RecommendResult


class RecommendationEngine:
    """Single entry point for track, artist, playlist, and genre recommendations.

    Loads corpus and model artifacts at init. Routes recommend() calls to the
    correct pipeline based on request_type. Per-playlist classifiers are loaded
    lazily from models_dir.

    Args:
        models_dir: Directory containing gmm_corpus.pkl, scaler_corpus.pkl,
            and per-playlist classifier_{slug}.pkl files.
        data_dir: Root data directory. Corpus loaded from
            data_dir/archived/spotify_train_data.csv and genre map from
            data_dir/archived/genres/genre_xy.csv.
        spotify_client: Optional SpotifyClient used only for playlist pipeline
            (fetching live playlist tracks). Engine is fully testable without it.
    """

    def __init__(
        self,
        models_dir: Path,
        data_dir: Path,
        spotify_client=None,
    ) -> None:
        # Load corpus
        corpus_path = data_dir / "archived" / "spotify_train_data.csv"
        self._corpus: pl.DataFrame = pl.read_csv(corpus_path)

        # Load genre map
        genre_map_path = data_dir / "archived" / "genres" / "genre_xy.csv"
        self._genre_map: pl.DataFrame = load_genre_map(genre_map_path)

        # Load GMM
        gmm_path = models_dir / "gmm_corpus.pkl"
        if not gmm_path.exists():
            raise FileNotFoundError(
                f"GMM model not found: {gmm_path}. "
                "Run `PYTHONPATH=src uv run python -m recommend.train` to generate it."
            )
        self._gmm: GaussianMixture = joblib.load(gmm_path)

        # Load scaler
        scaler_path = models_dir / "scaler_corpus.pkl"
        if not scaler_path.exists():
            raise FileNotFoundError(
                f"Scaler not found: {scaler_path}. "
                "Run `PYTHONPATH=src uv run python -m recommend.train` to generate it."
            )
        self._scaler: MinMaxScaler = joblib.load(scaler_path)

        self._models_dir: Path = models_dir
        self._classifier_cache: dict[str, Pipeline | None] = {}
        self._spotify_client = spotify_client

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
        if self._spotify_client is None:
            return RecommendResult(
                track_uris=[],
                track_ids=[],
                track_names=[],
                scores=[],
                pipeline_used="playlist",
                explanation=(
                    "Spotify client not configured. "
                    "Pass a SpotifyClient to RecommendationEngine to enable playlist recommendations."
                ),
            )

        try:
            from spotify.fetch import fetch_audio_features, fetch_playlist_tracks

            track_features_list = fetch_playlist_tracks(
                self._spotify_client, request.seed_id
            )
            if not track_features_list:
                return RecommendResult(
                    track_uris=[],
                    track_ids=[],
                    track_names=[],
                    scores=[],
                    pipeline_used="playlist",
                    explanation=f"Playlist '{request.seed_id}' appears to be empty or inaccessible.",
                )

            track_ids = [t.id for t in track_features_list]
            audio_features_list = fetch_audio_features(self._spotify_client, track_ids)

            # Build a Polars DataFrame with columns the pipeline needs
            audio_map = {af.id: af for af in audio_features_list}
            rows = []
            for tf in track_features_list:
                af = audio_map.get(tf.id)
                if af is None:
                    continue
                row: dict = {
                    "id": tf.id,
                    "track_name": tf.name,
                    "danceability": af.danceability,
                    "energy": af.energy,
                    "loudness": af.loudness,
                    "speechiness": af.speechiness,
                    "acousticness": af.acousticness,
                    "instrumentalness": af.instrumentalness,
                    "liveness": af.liveness,
                    "valence": af.valence,
                    "tempo": af.tempo,
                    "popularity": 0.0,
                    "top": 0.0,
                    "left": 0.0,
                    "key_mode": "",
                    "decade": "",
                }
                # Enrich from corpus if available
                corpus_match = self._corpus.filter(pl.col("id") == tf.id)
                if len(corpus_match) > 0:
                    corpus_row = corpus_match.row(0, named=True)
                    row["popularity"] = float(corpus_row.get("popularity", 0.0))
                    row["top"] = float(corpus_row.get("top", 0.0))
                    row["left"] = float(corpus_row.get("left", 0.0))
                    row["key_mode"] = corpus_row.get("key_mode", "")
                    row["decade"] = corpus_row.get("decade", "")
                rows.append(row)

            if not rows:
                return RecommendResult(
                    track_uris=[],
                    track_ids=[],
                    track_names=[],
                    scores=[],
                    pipeline_used="playlist",
                    explanation="No audio features available for playlist tracks.",
                )

            playlist_tracks_df = pl.DataFrame(rows)

        except Exception as exc:
            return RecommendResult(
                track_uris=[],
                track_ids=[],
                track_names=[],
                scores=[],
                pipeline_used="playlist",
                explanation=f"Failed to fetch playlist tracks: {exc}",
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
