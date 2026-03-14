# Changelog

## [Unreleased] — v2 Refactor in progress

### Phase 1 — Foundation ✓
- [x] `src/observability/logging.py` + `tracing.py` — structlog setup; OTLP tracing stub (replaces `utils/logger.py` + `utils/observability.py`)
- [x] `src/data/schemas.py` — Pydantic v2 schemas incl. `ListeningHistoryEntry` (replaces Marshmallow in `api/data/playlist_schema.py`)
- [x] `src/data/loader.py` — Polars data loader; Parquet cache; paths from `settings`; `enrich_categorical_features`, `tag_genre_categories` (replaces pandas + hardcoded paths in `api/data/playlists.py` + `analysis/data.py`)

### Phase 2 — Analysis core
- [ ] `src/analysis/core.py` — consolidate `analysis/data.py` + `analysis/genre.py` as pure Polars functions
- [ ] `src/analysis/similarity.py` — migrate `models/cosine.py` + `models/euclidean.py`, add hybrid method
- [ ] `src/analysis/clustering.py` — migrate `models/clustering.py` to Polars

### Phase 3 — LangGraph agent
- [ ] `src/agent/state.py` — TypedDict state schema
- [ ] `src/agent/nodes.py` — intent, analysis, action, synthesize nodes (Anthropic Haiku)
- [ ] `src/agent/graph.py` — StateGraph with conditional routing

### Phase 4 — MCP + RAG
- [ ] `src/mcp_server/tools.py` — wire stubs to real spotipy calls
- [ ] `src/rag/embeddings.py` — sentence-transformers wrapper for Chroma
- [ ] `src/rag/wiki_rag.py` — Wikipedia RAG

### Phase 5 — UI wiring + cleanup
- [ ] Wire `src/app/main.py` → LangGraph agent
- [ ] Delete `src/api/` and `src/models/` (superseded)

---

## [0.2.0] — 2026-03-09 — Infrastructure & credentials refactor

### Added
- `src/actions/spotify_actions.py` — spotipy-based OAuth with token caching + write ops (`create_playlist`, `add_tracks`, `create_playlist_with_tracks`)
- `src/mcp_server/server.py` — minimal FastMCP server with stubbed tools (`get_playlist_tracks`, `get_track_features`, `search_tracks`)
- `src/app/main.py` — Chainlit entry point (stubs, replaces Flask app)
- `src/utils/config.py` — rewritten with `pydantic-settings`; all env vars in one place
- `.env.example` — Anthropic-first, removed OpenAI, added `SPOTIFY_USER_ID`, local embeddings
- `.gitignore` — added `.spotify_cache`, data dirs, logs
- `setup.sh` — dev onboarding script (replaces `docker-run.sh`)
- `CHANGELOG.md` — this file

### Changed
- `docker-compose.yml` — full rewrite: removed OpenAI, added MCP port 8765, profiles for Jaeger (`--profile observability`) and Postgres (`--profile database`), healthcheck, networking
- `Dockerfile` — `python:3.13` → `python:3.11-slim`; fixed uv install (`pip install uv` replaces broken `curl | sh` + wrong PATH)
- `pyproject.toml` — removed `langchain-openai`, `openai`, `streamlit`, `python-dotenv`; added `langchain-anthropic`, `yellowbrick`; fixed `opentelemetry-exporter-jaeger` (last release was 1.21.0, broken at `>=1.22.0`) → `opentelemetry-exporter-otlp`; fixed `opentelemetry-instrumentation>=0.43b0` → `>=0.44.0`; bumped `mcp>=0.9.0` → `>=1.0.0`; removed broken `[project.scripts]`; added `[tool.hatch.build.targets.wheel]` for src layout; restored `[tool.uv] dev-dependencies`
- `Makefile` — fixed `COMPOSE_INFRA_DEV` undefined ref; switched to `docker compose`; added `app`, `mcp-server`, `format`, `test` targets; added `PYTHONPATH=src`

### Removed
- `docker-run.sh` — replaced by `setup.sh`
- `refactor_plan.md` — replaced by this changelog

---

## [0.1.0] — Original Flask app

### Features
- Flask OAuth flow for Spotify authentication
- Spotify API client for playlist + audio + artist feature requests (raw `requests`, pandas DataFrames)
- Genre mapping via Every Noise at Once (ENOA) coordinates
- IsolationForest outlier detection per playlist
- Cosine similarity recommendations (`models/cosine.py`)
- Euclidean distance recommendations (`models/euclidean.py`)
- Spectral clustering for remix playlists (`models/clustering.py`)
- sklearn classifier pipeline — LogisticRegression, DecisionTree, RandomForest with RFE (`models/classifiers.py`)
- Marshmallow schemas for Spotify API response validation
- EDA notebook and plots (`analysis/output/`)
- Basic Python logging with uvicorn formatter
