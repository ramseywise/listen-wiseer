# Changelog

## [Unreleased] — Phase 3: LangGraph Agent

_Nothing yet — see `.claude/docs/PLAN.md` Phase 3 steps._

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
