# Changelog

## [Unreleased] — Phase 4b: Long-Term Memory for ENOA

### P0 — Make agent_node async
- Modified: `src/agent/nodes.py` — `agent_node` changed to `async def`, uses `await _llm_with_tools.ainvoke()`
- Modified: `tests/unit/agent/test_graph.py` — all mocks updated from `.invoke` to `.ainvoke`
- Tests: 280 passed, 32 failed (pre-existing duckdb.IOError), 3 skipped — no regressions
- Deviations: none

### Step 4.1 — History overflow: trim messages
- Added: `trim_history` node in `src/agent/nodes.py` — trims to `max_history_messages` (default 20) using `trim_messages(strategy="last", start_on="human")`
- Modified: `src/agent/graph.py` — graph now `START → trim_history → agent → [route] → ...`
- Modified: `src/utils/config.py` — added `max_history_messages: int = 20`
- Added: `tests/unit/agent/test_nodes.py` — 3 tests (under/over/at limit)
- Tests: 283 passed, 32 failed (pre-existing), 3 skipped
- Deviations: test file tests trim logic directly (replicates function) to avoid DuckDB import chain; not ideal but matches existing pattern in test_graph.py where all agent tests hit this blocker

### P2 — Add recursion_limit to build_graph
- Modified: `src/agent/graph.py` — added `recursion_limit=RECURSION_LIMIT` to `builder.compile()`
- Tests: 280 passed, 32 failed (pre-existing), 3 skipped — no regressions
- Deviations: none

### P1 — Wire user_id through Chainlit
- Modified: `src/app/main.py` — added `langgraph_user_id` to config dict, sourced from `settings.spotify_user_id`
- Tests: 280 passed, 32 failed (pre-existing), 3 skipped — no regressions
- Deviations: none

---

## [0.5.0] — 2026-04-04 — Phase 3a/3b: Feature engineering + training pipeline

### Added
- **`src/paths.py`** — `REPO_ROOT`, `MODELS_DIR`, `DATA_DIR`, `DB_PATH`, `CACHE_DIR`, `ARCHIVED_DIR` — single path anchor for all modules
- **`src/recommend/preprocessing.py`** — full feature engineering pipeline (`build_feature_matrix`):
  - `load_corpus_from_db` — reads `track_profile` view from DuckDB
  - `add_collaborative_features` — `n_playlists`, `playlist_diversity`, `fave_score`
  - `add_temporal_features` — `year_normalized`, `years_since_release`, `duration_ms_normalized`
  - `compute_artist_enoa_centroid` — ENOA spatial centroid per artist via `track_artists` join
  - `compute_artist_medians` / `compute_genre_medians` — imputation source tables
  - `impute_missing_features` — artist → genre → global median cascade for NULL audio features
  - `propagate_playlist_profiles` — fills genre/cluster columns from playlist membership
  - `compute_track2vec` / `store_track2vec` / `load_track2vec` — Track2Vec (Word2Vec on playlist co-occurrence, 64d) via gensim; stored in `track_embeddings` DuckDB table
- **`src/recommend/train.py`** — complete training script: reads DuckDB, calls `build_feature_matrix`, fits GMM + scaler + per-playlist LightGBM classifiers, writes `models/*.pkl` and `data/cache/corpus_features.parquet`
- **Track2Vec embeddings wired into inference** (`src/recommend/pipelines.py`):
  - `_add_embedding_similarity` helper — cosine(seed t2v, candidate t2v) using `t2v_0..t2v_63` corpus columns
  - Called before `rerank_candidates` in `TrackPipeline`, `ArtistPipeline`, `PlaylistPipeline`, `GenrePipeline`
- **450 new unit tests** (`tests/unit/test_preprocessing.py`, expanded `test_train.py`, `test_pipelines.py`, `test_classifiers.py`, `test_clustering.py`)

### Changed
- **`src/mcp_server/server.py`** — imports `MODELS_DIR`, `DATA_DIR` from `paths` (removed inline `Path(__file__)` computation)
- **`src/recommend/engine.py`** — imports paths from `paths`; corpus loaded from parquet cache; genre map loaded from DuckDB at init
- **`src/recommend/modules/genre.py`** — `load_genre_map_from_db` reads from DuckDB instead of CSV
- **`src/etl/db.py`** — `track_profile` view now includes `af.features_source`; `track_embeddings` table added to DDL; `audio_features.features_source` migration added
- **`src/recommend/train.py`** bugfixes:
  - Removed `read_only=True` on training connection (view refresh requires write access)
  - `init_schema` called before `build_feature_matrix` to refresh `track_profile` view
  - ENOA/spatial columns (`top`, `left`, `artist_enoa_top`, `artist_enoa_left`) filled with 0.0 before GMM fit

---

## [0.4.0] — 2026-04-04 — ETL rebuild, Last.fm integration, pre-commit

### Added
- **Last.fm API integration** (`src/etl/sync.py`) — enriches tracks with play count, listener count, tags; 227-test suite (`tests/unit/test_lastfm.py`, `tests/unit/test_sync.py`)
- **Pre-commit config** (`.pre-commit-config.yaml`) — ruff lint/format + pyright hooks wired in
- **`.claude/` skills and commands** — `research_synthesis.md`, `review_validate_plan.md`, full CLAUDE.md expansion

### Changed
- **ETL rewrite** (`src/etl/bootstrap.py`, `sync.py`, `loader.py`) — significant refactor; `sync.py` now +263/−133 lines with Last.fm path
- **Spotify client** (`src/spotify/fetch.py`) — refactored fetch layer; `auth.py` + `client.py` simplified (−79 lines net)
- **Spotify sync** (`src/etl/sync.py`) — refresh flow simplified, auth token handling cleaned up
- **Recommend pipeline tests** — engine, genre, pipelines, train tests expanded (+300/−128 lines)
- **MCP server** — minor fixes alongside pre-commit wiring

---

## [0.3.0] — 2026-03-13 — Recommendation layer (Phase 2 rebuild)

### Added
- `src/recommend/schemas.py` — `RecommendRequest`, `RecommendResult` (Pydantic v2)
- `src/recommend/modules/similarity.py` — weighted cosine similarity, Camelot harmonic distance, tempo compatibility, MMR selection
- `src/recommend/modules/clustering.py` — GMM soft clustering, `filter_corpus_by_cluster`
- `src/recommend/modules/classifiers.py` — LightGBM + `CalibratedClassifierCV` reranker, per-playlist pkl I/O
- `src/recommend/modules/genre.py` — ENOA spatial proximity, genre zone filtering
- `src/recommend/train.py` — fits GMM + scaler + per-playlist classifiers → `models/*.pkl`
- `src/recommend/pipelines.py` — `TrackPipeline`, `ArtistPipeline`, `PlaylistPipeline`, `GenrePipeline`
- `src/recommend/engine.py` — `RecommendationEngine` singleton: loads artifacts, lazy classifier cache, routes by request_type
- `src/mcp_server/server.py` — 4 new MCP tools: `recommend_similar_tracks`, `recommend_for_artist`, `recommend_for_playlist`, `recommend_by_genre`
- `models/.gitkeep` — artifact storage directory
- `lightgbm>=4.3.0` added to dependencies
- 139 unit tests across `tests/unit/recommend/`

### Removed
- Legacy `src/models/clustering.py`, `classifiers.py`, `cosine.py`, `__init__.py` (pandas, hardcoded paths)

---

## [0.2.0] — 2026-03-09 — Infrastructure & credentials refactor

### Added
- `src/spotify/` — custom OAuth httpx client, fetch/write ops, `SpotifyActions`
- `src/mcp_server/server.py` — FastMCP server with stubbed Spotify tools
- `src/app/main.py` — Chainlit entry point (stub)
- `src/utils/config.py` — pydantic-settings, all env vars centralised
- `src/utils/exceptions.py` — typed exception hierarchy
- `src/etl/` — DuckDB bootstrap/sync, Polars loader with Parquet cache
- `setup.sh`, `.env.example`, `CHANGELOG.md`

### Changed
- `docker-compose.yml` — full rewrite; MCP port 8765; Jaeger + Postgres profiles
- `Dockerfile` — python:3.11-slim; fixed uv install
- `pyproject.toml` — removed OpenAI/Streamlit; added Anthropic, LangGraph, LightGBM

---

## [0.1.0] — Original Flask app

- Flask OAuth + Spotify API client (pandas, requests)
- Genre mapping via ENOA coordinates
- IsolationForest outlier detection
- Cosine/Euclidean similarity, Spectral clustering, sklearn classifier pipeline
- Marshmallow schemas
