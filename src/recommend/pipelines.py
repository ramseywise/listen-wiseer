"""Four recommendation pipeline classes and the MMR diversity helper.

Each pipeline accepts pre-loaded artifacts (corpus, GMM, scaler, optional classifier)
and returns a RecommendResult. No Spotify I/O; no artifact loading.
"""

from __future__ import annotations

import numpy as np
import polars as pl
from sklearn.mixture import GaussianMixture
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler

from recommend.modules.classifiers import rerank_candidates
from recommend.modules.clustering import (
    build_cluster_features,
    predict_cluster_probs,
)
from recommend.modules.genre import expand_genre_zone
from recommend.modules.similarity import (
    SIMILARITY_FEATURES,
    find_similar,
    playlist_centroid,
)
from recommend.schemas import RecommendRequest, RecommendResult
from utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Embedding similarity helper
# ---------------------------------------------------------------------------

T2V_PREFIX = "t2v_"


def _add_embedding_similarity(
    candidates: pl.DataFrame,
    seed_id: str | None,
    corpus: pl.DataFrame,
) -> pl.DataFrame:
    """Add 'embedding_similarity' column to candidates using Track2Vec cosine similarity.

    Looks up the seed track's t2v embedding from the corpus, then computes cosine
    similarity against each candidate's t2v embedding. Falls back to 0.0 if embeddings
    are absent or the seed track has no embedding.

    Args:
        candidates: Candidate DataFrame (subset of corpus rows).
        seed_id: Track ID of the seed track (may be None for centroid-based queries).
        corpus: Full corpus with t2v_* columns.

    Returns:
        candidates with 'embedding_similarity' column added (or replaced).
    """
    t2v_cols = [c for c in corpus.columns if c.startswith(T2V_PREFIX)]
    if not t2v_cols or not seed_id:
        return candidates.with_columns(pl.lit(0.0).alias("embedding_similarity"))

    # Look up seed embedding
    seed_rows = corpus.filter(pl.col("id") == seed_id)
    if seed_rows.is_empty():
        return candidates.with_columns(pl.lit(0.0).alias("embedding_similarity"))

    seed_vec = seed_rows.select(t2v_cols).to_numpy()[0].astype(np.float64)
    seed_norm = np.linalg.norm(seed_vec)
    if seed_norm == 0.0:
        return candidates.with_columns(pl.lit(0.0).alias("embedding_similarity"))

    # Only compute for candidates that have the t2v columns
    cand_t2v_cols = [c for c in t2v_cols if c in candidates.columns]
    if not cand_t2v_cols:
        return candidates.with_columns(pl.lit(0.0).alias("embedding_similarity"))

    cand_mat = candidates.select(cand_t2v_cols).to_numpy().astype(np.float64)
    cand_norms = np.linalg.norm(cand_mat, axis=1, keepdims=True)
    cand_norms = np.where(cand_norms == 0.0, 1.0, cand_norms)
    sims = (cand_mat / cand_norms) @ (seed_vec / seed_norm)

    return candidates.with_columns(pl.Series("embedding_similarity", sims.tolist()))


# ---------------------------------------------------------------------------
# MMR helper
# ---------------------------------------------------------------------------


def _mmr_select(
    candidates: pl.DataFrame,
    query: np.ndarray,
    k: int,
    lambda_: float = 0.7,
    feature_cols: list[str] = SIMILARITY_FEATURES,
) -> pl.DataFrame:
    """Maximal Marginal Relevance selection for diversity-aware top-k.

    Iteratively picks the candidate that maximises:
        lambda_ * sim(c, query) - (1 - lambda_) * max(sim(c, selected))

    Args:
        candidates: DataFrame of candidate tracks. Must contain feature_cols.
        query: (n_features,) query feature vector aligned to feature_cols.
        k: Number of tracks to select.
        lambda_: Trade-off between relevance (1.0) and diversity (0.0).
        feature_cols: Feature columns used for cosine similarity.

    Returns:
        DataFrame of up to k selected rows in selection order.
    """
    if len(candidates) == 0:
        return candidates

    if len(candidates) <= k:
        return candidates

    # Filter to only columns that exist in the candidates df
    available_cols = [c for c in feature_cols if c in candidates.columns]
    if not available_cols:
        return candidates.head(k)

    # Align query to available_cols only
    feature_indices = [feature_cols.index(c) for c in available_cols]
    query_vec = query[feature_indices].astype(np.float64)

    # Extract feature matrix
    X = candidates.select(available_cols).to_numpy().astype(np.float64)
    n = len(X)

    # Normalise rows for cosine
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        if denom == 0.0:
            return 0.0
        return float(np.clip(np.dot(a, b) / denom, 0.0, 1.0))

    # Relevance scores: sim(c, query) for all candidates
    rel_scores = np.array([_cosine(X[i], query_vec) for i in range(n)])

    selected_indices: list[int] = []
    remaining = list(range(n))

    for _ in range(k):
        if not remaining:
            break

        if not selected_indices:
            # First pick: pure relevance
            best_idx = max(remaining, key=lambda i: rel_scores[i])
        else:
            # Compute max sim to already selected set for each remaining candidate
            sel_X = X[selected_indices]

            def _max_sim_to_selected(i: int, _sel_X: np.ndarray = sel_X) -> float:
                return max(_cosine(X[i], _sel_X[j]) for j in range(len(_sel_X)))

            best_idx = max(
                remaining,
                key=lambda i: lambda_ * rel_scores[i] - (1 - lambda_) * _max_sim_to_selected(i),
            )

        selected_indices.append(best_idx)
        remaining.remove(best_idx)

    return candidates[selected_indices]


# ---------------------------------------------------------------------------
# Result construction helper
# ---------------------------------------------------------------------------


def _build_result(
    result_df: pl.DataFrame,
    request: RecommendRequest,
    explanation: str,
) -> RecommendResult:
    """Construct a RecommendResult from a candidates DataFrame.

    Args:
        result_df: Final ranked DataFrame.
        request: The originating recommendation request.
        explanation: Human-readable summary for the agent.

    Returns:
        Populated RecommendResult.
    """
    if len(result_df) == 0:
        return RecommendResult(
            track_uris=[],
            track_ids=[],
            track_names=[],
            scores=[],
            pipeline_used=request.request_type,
            explanation=explanation,
        )

    track_ids = result_df["id"].to_list()
    track_uris = [f"spotify:track:{tid}" for tid in track_ids]

    if "track_name" in result_df.columns:
        track_names = result_df["track_name"].to_list()
    else:
        track_names = track_ids

    if "rerank_score" in result_df.columns:
        scores = result_df["rerank_score"].to_list()
    elif "similarity_score" in result_df.columns:
        scores = result_df["similarity_score"].to_list()
    else:
        scores = [0.0] * len(track_ids)

    return RecommendResult(
        track_uris=track_uris,
        track_ids=track_ids,
        track_names=[str(n) for n in track_names],
        scores=[float(s) for s in scores],
        pipeline_used=request.request_type,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Cluster filter with empty-corpus fallback
# ---------------------------------------------------------------------------


def _cluster_filter(
    corpus: pl.DataFrame,
    query_features: np.ndarray,
    gmm: GaussianMixture,
    scaler: MinMaxScaler,
) -> pl.DataFrame:
    """Run cluster filter; fall back to full corpus if result is empty.

    The query_features vector is in SIMILARITY_FEATURES space (12-dim). We derive
    the query's cluster membership by finding the corpus row with the highest
    cosine similarity to the query and using its cluster probability vector.
    If the corpus is empty or cluster filter yields nothing, returns the full
    corpus annotated with cluster columns.

    Args:
        corpus: Full candidate corpus (must contain SIMILARITY_FEATURES columns
            plus key_mode and decade for build_cluster_features).
        query_features: (n_similarity_features,) query vector aligned to
            SIMILARITY_FEATURES.
        gmm: Fitted GaussianMixture.
        scaler: Fitted MinMaxScaler matching the GMM.

    Returns:
        Filtered (or full) corpus with cluster_id and cluster_prob columns.
    """
    if len(corpus) == 0:
        return corpus

    # Compute cluster features and probs for the full corpus once
    corpus_features, _ = build_cluster_features(corpus, scaler, fit_scaler=False)
    corpus_probs = predict_cluster_probs(corpus_features, gmm)
    cluster_ids_all = np.argmax(corpus_probs, axis=1).astype(np.int32)
    cluster_probs_all = corpus_probs[np.arange(len(corpus_probs)), cluster_ids_all]

    # Find the corpus row most similar to query (in SIMILARITY_FEATURES space)
    # to use as a proxy for query cluster membership
    try:
        from recommend.modules.similarity import (
            DEFAULT_WEIGHTS,
            compute_weighted_cosine,
        )

        available = [c for c in SIMILARITY_FEATURES if c in corpus.columns]
        if available and len(query_features) >= len(available):
            feat_indices = [SIMILARITY_FEATURES.index(c) for c in available]
            q_vec = query_features[feat_indices].astype(np.float64)
            X = corpus.select(available).to_numpy().astype(np.float64)
            weights_arr = np.array(
                [DEFAULT_WEIGHTS.get(f, 1.0) for f in available], dtype=np.float64
            )
            sims = compute_weighted_cosine(X, q_vec, weights_arr)
            nearest_idx = int(np.argmax(sims))
            query_probs = corpus_probs[nearest_idx]
        else:
            # Uniform over all clusters as fallback
            query_probs = np.ones(gmm.n_components) / gmm.n_components
    except Exception:
        query_probs = np.ones(gmm.n_components) / gmm.n_components

    # Determine which clusters are relevant to the query
    min_prob = 0.05
    relevant_clusters = {int(c) for c in np.where(query_probs >= min_prob)[0]}

    mask = np.array([int(cid) in relevant_clusters for cid in cluster_ids_all])
    filtered = corpus.filter(pl.Series(mask))

    if len(filtered) == 0:
        # Fall back: annotate full corpus
        filtered = corpus.with_columns(
            [
                pl.Series("cluster_id", cluster_ids_all),
                pl.Series("cluster_prob", cluster_probs_all),
            ]
        )
        return filtered

    # Annotate filtered subset
    cluster_ids_filtered = cluster_ids_all[mask]
    cluster_probs_filtered = cluster_probs_all[mask]
    filtered = filtered.with_columns(
        [
            pl.Series("cluster_id", cluster_ids_filtered),
            pl.Series("cluster_prob", cluster_probs_filtered),
        ]
    )
    return filtered


# ---------------------------------------------------------------------------
# TrackPipeline
# ---------------------------------------------------------------------------


class TrackPipeline:
    """Recommend tracks similar to a single seed track."""

    def run(
        self,
        request: RecommendRequest,
        query_features: np.ndarray,
        corpus: pl.DataFrame,
        gmm: GaussianMixture,
        scaler: MinMaxScaler,
        classifier: Pipeline | None = None,
        weights: dict[str, float] | None = None,
    ) -> RecommendResult:
        """Run the track similarity pipeline.

        Steps:
        1. Cluster filter to narrow candidates.
        2. Weighted cosine similarity -> top-100.
        3. Optional classifier rerank.
        4. MMR selection -> final k tracks.

        Args:
            request: The recommendation request (seed_id is a track ID).
            query_features: (n_features,) feature vector for the seed track aligned to
                SIMILARITY_FEATURES. Used for both cluster proxy lookup and cosine similarity.
            corpus: Full corpus DataFrame with SIMILARITY_FEATURES + key_mode + decade columns.
            gmm: Fitted GaussianMixture for cluster filtering.
            scaler: Fitted MinMaxScaler matching the GMM.
            classifier: Optional per-playlist LightGBM Pipeline for reranking.
            weights: Per-feature weights for cosine similarity.

        Returns:
            RecommendResult with up to request.k tracks.
        """
        k = request.k

        # Step 1: cluster filter (uses query as proxy to determine relevant clusters)
        filtered = _cluster_filter(corpus, query_features, gmm, scaler)

        # Step 2: cosine similarity -> top-100
        candidates = find_similar(corpus=filtered, query=query_features, k=100, weights=weights)

        # Step 3: optional rerank
        playlist_profile: dict = {}
        if classifier is not None and len(candidates) > 0:
            if "cluster_prob" not in candidates.columns:
                candidates = candidates.with_columns(pl.lit(0.0).alias("cluster_prob"))
            candidates = _add_embedding_similarity(candidates, request.seed_id, corpus)
            playlist_profile = {"modal_key": "", "mean_tempo": 0.0}
            try:
                candidates = rerank_candidates(candidates, classifier, playlist_profile)
                candidates = candidates.head(k * 2)
            except Exception as exc:
                log.warning("pipeline.rerank.failed", error=str(exc))

        # Step 4: MMR
        result_df = _mmr_select(candidates, query_features, k)

        k_found = len(result_df)
        explanation = f"Found {k_found} tracks similar to {request.seed_id}"
        return _build_result(result_df, request, explanation)


# ---------------------------------------------------------------------------
# ArtistPipeline
# ---------------------------------------------------------------------------


class ArtistPipeline:
    """Recommend tracks matching an artist's sonic profile."""

    def run(
        self,
        request: RecommendRequest,
        artist_track_features: pl.DataFrame,
        corpus: pl.DataFrame,
        gmm: GaussianMixture,
        scaler: MinMaxScaler,
        classifier: Pipeline | None = None,
        weights: dict[str, float] | None = None,
    ) -> RecommendResult:
        """Run the artist profile pipeline.

        Steps:
        1. Compute centroid of artist's tracks in SIMILARITY_FEATURES space.
        2. Then identical to TrackPipeline from cluster filter onwards.

        Args:
            request: The recommendation request (seed_id is an artist ID).
            artist_track_features: DataFrame of the artist's tracks in corpus
                (must contain SIMILARITY_FEATURES columns).
            corpus: Full corpus DataFrame.
            gmm: Fitted GaussianMixture.
            scaler: Fitted MinMaxScaler.
            classifier: Optional reranker.
            weights: Per-feature weights for cosine similarity.

        Returns:
            RecommendResult with up to request.k tracks.
        """
        k = request.k

        if len(artist_track_features) == 0:
            return RecommendResult(
                track_uris=[],
                track_ids=[],
                track_names=[],
                scores=[],
                pipeline_used=request.request_type,
                explanation=f"No tracks found in corpus for artist {request.seed_id}",
            )

        # Step 1: centroid of artist tracks
        centroid = playlist_centroid(artist_track_features, SIMILARITY_FEATURES)

        # Steps 2-4: identical to TrackPipeline (using centroid as query)
        filtered = _cluster_filter(corpus, centroid, gmm, scaler)
        candidates = find_similar(corpus=filtered, query=centroid, k=100, weights=weights)

        if classifier is not None and len(candidates) > 0:
            if "cluster_prob" not in candidates.columns:
                candidates = candidates.with_columns(pl.lit(0.0).alias("cluster_prob"))
            candidates = _add_embedding_similarity(candidates, None, corpus)
            playlist_profile: dict = {"modal_key": "", "mean_tempo": 0.0}
            try:
                candidates = rerank_candidates(candidates, classifier, playlist_profile)
                candidates = candidates.head(k * 2)
            except Exception as exc:
                log.warning("pipeline.rerank.failed", error=str(exc))

        result_df = _mmr_select(candidates, centroid, k)
        k_found = len(result_df)
        explanation = f"Found {k_found} tracks matching artist's sonic profile"
        return _build_result(result_df, request, explanation)


# ---------------------------------------------------------------------------
# PlaylistPipeline
# ---------------------------------------------------------------------------


class PlaylistPipeline:
    """Recommend tracks to add to an existing playlist."""

    def run(
        self,
        request: RecommendRequest,
        playlist_tracks: pl.DataFrame,
        corpus: pl.DataFrame,
        gmm: GaussianMixture,
        scaler: MinMaxScaler,
        classifier: Pipeline | None = None,
        weights: dict[str, float] | None = None,
    ) -> RecommendResult:
        """Run the playlist extension pipeline.

        Steps:
        1. Compute playlist profile: centroid, modal_key, mean_tempo.
        2. Exclude playlist track IDs from corpus.
        3. Cluster filter.
        4. Weighted cosine to centroid -> top-100.
        5. Optional classifier rerank with playlist_profile.
        6. Cluster-diverse sampling: at most k//n_unique_clusters per cluster,
           fill remaining slots from top scorers.

        Args:
            request: The recommendation request (seed_id is a playlist ID).
            playlist_tracks: DataFrame of current playlist tracks
                (must contain SIMILARITY_FEATURES + key_mode + tempo + id).
            corpus: Full corpus DataFrame.
            gmm: Fitted GaussianMixture.
            scaler: Fitted MinMaxScaler.
            classifier: Optional reranker.
            weights: Per-feature weights for cosine similarity.

        Returns:
            RecommendResult with up to request.k tracks, excluding playlist tracks.
        """
        k = request.k

        if len(playlist_tracks) == 0:
            return RecommendResult(
                track_uris=[],
                track_ids=[],
                track_names=[],
                scores=[],
                pipeline_used=request.request_type,
                explanation="Playlist is empty — no profile to match",
            )

        # Step 1: playlist profile
        centroid = playlist_centroid(playlist_tracks, SIMILARITY_FEATURES)

        modal_key = ""
        if "key_mode" in playlist_tracks.columns:
            key_modes = playlist_tracks["key_mode"].to_list()
            modal_key = max(set(key_modes), key=key_modes.count)

        mean_tempo = 0.0
        if "tempo" in playlist_tracks.columns:
            mean_tempo = float(playlist_tracks["tempo"].mean())

        playlist_profile = {
            "centroid": centroid,
            "modal_key": modal_key,
            "mean_tempo": mean_tempo,
        }

        # Step 2: exclude playlist track IDs
        playlist_ids: set[str] = set()
        if "id" in playlist_tracks.columns:
            playlist_ids = set(playlist_tracks["id"].to_list())

        working_corpus = corpus
        if playlist_ids and "id" in corpus.columns:
            working_corpus = corpus.filter(~pl.col("id").is_in(list(playlist_ids)))

        if len(working_corpus) == 0:
            return RecommendResult(
                track_uris=[],
                track_ids=[],
                track_names=[],
                scores=[],
                pipeline_used=request.request_type,
                explanation="No corpus tracks remain after excluding playlist tracks",
            )

        # Step 3: cluster filter
        filtered = _cluster_filter(working_corpus, centroid, gmm, scaler)

        # Step 4: cosine similarity -> top-100
        candidates = find_similar(corpus=filtered, query=centroid, k=100, weights=weights)

        # Step 5: optional classifier rerank
        if classifier is not None and len(candidates) > 0:
            if "cluster_prob" not in candidates.columns:
                candidates = candidates.with_columns(pl.lit(0.0).alias("cluster_prob"))
            candidates = _add_embedding_similarity(candidates, None, corpus)
            try:
                candidates = rerank_candidates(candidates, classifier, playlist_profile)
                candidates = candidates.head(k * 2)
            except Exception as exc:
                log.warning("pipeline.rerank.failed", error=str(exc))

        # Step 6: cluster-diverse sampling
        result_df = self._cluster_diverse_sample(candidates, k)

        k_found = len(result_df)
        explanation = f"Found {k_found} tracks to add to your playlist"
        return _build_result(result_df, request, explanation)

    @staticmethod
    def _cluster_diverse_sample(candidates: pl.DataFrame, k: int) -> pl.DataFrame:
        """Sample k tracks from candidates with cluster diversity.

        Takes at most k // n_unique_clusters from each cluster, then fills
        remaining slots from top scorers not yet selected.

        Args:
            candidates: DataFrame with optional 'cluster_id' column and a score column.
            k: Target number of tracks.

        Returns:
            DataFrame of up to k rows.
        """
        if len(candidates) == 0:
            return candidates

        if len(candidates) <= k:
            return candidates

        # Determine score column
        score_col = (
            "rerank_score"
            if "rerank_score" in candidates.columns
            else "similarity_score"
            if "similarity_score" in candidates.columns
            else None
        )

        if "cluster_id" not in candidates.columns:
            # No cluster info — just return top-k by score
            if score_col:
                return candidates.sort(score_col, descending=True).head(k)
            return candidates.head(k)

        n_unique = candidates["cluster_id"].n_unique()
        per_cluster = max(1, k // n_unique)

        selected_rows: list[pl.DataFrame] = []
        for cluster_id_val in candidates["cluster_id"].unique().to_list():
            cluster_df = candidates.filter(pl.col("cluster_id") == cluster_id_val)
            if score_col:
                cluster_df = cluster_df.sort(score_col, descending=True)
            selected_rows.append(cluster_df.head(per_cluster))

        selected = pl.concat(selected_rows)

        if len(selected) >= k:
            if score_col:
                return selected.sort(score_col, descending=True).head(k)
            return selected.head(k)

        # Fill remaining from top scorers not yet selected
        selected_ids = set(selected["id"].to_list()) if "id" in selected.columns else set()
        remaining = candidates
        if selected_ids and "id" in candidates.columns:
            remaining = candidates.filter(~pl.col("id").is_in(list(selected_ids)))

        needed = k - len(selected)
        if score_col:
            remaining = remaining.sort(score_col, descending=True)
        filler = remaining.head(needed)

        result = pl.concat([selected, filler])
        if score_col:
            result = result.sort(score_col, descending=True)
        return result.head(k)


# ---------------------------------------------------------------------------
# GenrePipeline
# ---------------------------------------------------------------------------


class GenrePipeline:
    """Recommend tracks within a genre's ENOA spatial zone."""

    def run(
        self,
        request: RecommendRequest,
        genre_map: pl.DataFrame,
        corpus: pl.DataFrame,
        gmm: GaussianMixture,
        scaler: MinMaxScaler,
        classifier: Pipeline | None = None,
        enoa_radius: float = 1500.0,
    ) -> RecommendResult:
        """Run the genre zone pipeline.

        Steps:
        1. Expand genre_name to ENOA zone (filter corpus by spatial proximity).
        2. If zone is empty: return empty result with explanation.
        3. Cluster filter within zone.
        4. Weighted cosine (uniform weights) -> top-100.
        5. Optional classifier rerank.
        6. MMR -> final k.

        Args:
            request: The recommendation request (seed_id is a genre name).
            genre_map: DataFrame with [first_genre, top, left] columns.
            corpus: Full corpus with SIMILARITY_FEATURES + top + left columns.
            gmm: Fitted GaussianMixture.
            scaler: Fitted MinMaxScaler.
            classifier: Optional reranker.
            enoa_radius: Spatial radius for genre zone membership.

        Returns:
            RecommendResult with up to request.k tracks, or empty if genre unknown.
        """
        k = request.k
        genre_name = request.seed_id

        # Step 1: expand genre zone
        zone_corpus = expand_genre_zone(genre_name, genre_map, corpus, radius=enoa_radius)

        # Step 2: empty zone -> graceful failure
        if len(zone_corpus) == 0:
            return RecommendResult(
                track_uris=[],
                track_ids=[],
                track_names=[],
                scores=[],
                pipeline_used=request.request_type,
                explanation=(
                    f"Genre '{genre_name}' not found in the ENOA map. "
                    "Try a different genre name or spelling."
                ),
            )

        # Derive zone centroid as query for cosine similarity
        zone_centroid = playlist_centroid(zone_corpus, SIMILARITY_FEATURES)

        # Step 3: cluster filter within zone
        filtered = _cluster_filter(zone_corpus, zone_centroid, gmm, scaler)

        # Step 4: cosine (uniform weights) -> top-100
        candidates = find_similar(corpus=filtered, query=zone_centroid, k=100, weights=None)

        # Step 5: optional classifier rerank
        if classifier is not None and len(candidates) > 0:
            if "cluster_prob" not in candidates.columns:
                candidates = candidates.with_columns(pl.lit(0.0).alias("cluster_prob"))
            candidates = _add_embedding_similarity(candidates, None, corpus)
            playlist_profile: dict = {"modal_key": "", "mean_tempo": 0.0}
            try:
                candidates = rerank_candidates(candidates, classifier, playlist_profile)
                candidates = candidates.head(k * 2)
            except Exception as exc:
                log.warning("pipeline.rerank.failed", error=str(exc))

        # Step 6: MMR
        result_df = _mmr_select(candidates, zone_centroid, k)

        k_found = len(result_df)
        explanation = f"Found {k_found} tracks in the {genre_name} zone"
        return _build_result(result_df, request, explanation)
