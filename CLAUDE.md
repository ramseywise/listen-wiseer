# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**listen-wiseer** is an intelligent Spotify music recommendation agent built with:
- **LLM**: Claude Haiku (`claude-haiku-4-5-20251001`) via Anthropic SDK
- **Agent orchestration**: LangGraph
- **Chat UI**: Chainlit
- **Data processing**: Polars (not pandas)
- **MCP server**: FastMCP exposing Spotify tools to the agent
- **RAG**: Wikipedia + ChromaDB + local sentence-transformers embeddings
- **Spotify auth**: custom OAuth via httpx (Authorization Code Flow, token cached at `.spotify_cache`)
- **Clustering**: Similarity measures for content clustering

## Commands

```bash
# Setup (first time)
bash setup.sh

# Run the Chainlit UI
make app         # or: PYTHONPATH=src uv run chainlit run src/app/main.py

# Run the MCP server (also triggers Spotify OAuth on first run)
make mcp-server

# Bootstrap DuckDB from archived CSVs
make init-db     # or: PYTHONPATH=src uv run python -m etl.bootstrap

# Sync live Spotify data into DuckDB (requires .spotify_cache)
make data-sync   # or: PYTHONPATH=src uv run python -m etl.sync

# Docker
make infra-up    # start containers
make infra-down  # stop containers
make infra-up ARGS="--profile observability"  # include Jaeger

# Tests
make test                  # full suite
make test-unit             # unit tests only (fast, no Spotify required)
uv run pytest tests/unit/test_data_loader.py::test_name -v

# Code quality
make lint        # ruff check + format check
make format      # ruff fix + format
```

## Architecture

### v2 (active development)

- **`src/app/main.py`** — Chainlit entry point; currently a stub (TODO: wire to LangGraph agent)
- **`src/utils/exceptions.py`** — typed exception hierarchy: `ListenWiseerError → SpotifyClientError → SpotifyAuthError`, `DataLoadError`, `ConfigurationError`
- **`src/utils/schemas.py`** — Pydantic v2 models: `TrackFeatures`, `AudioFeatures`, `ArtistFeatures`, `PlaylistTrack`, `ListeningHistoryEntry`
- **`src/utils/config.py`** — Pydantic Settings; all config via environment variables
- **`src/utils/const.py`** — Read-only constants: audio feature columns, genre lists, playlist IDs
- **`src/spotify/auth.py`** — custom OAuth: browser flow, token exchange, refresh, `.spotify_cache`
- **`src/spotify/client.py`** — httpx wrapper with Bearer token injection; raises `SpotifyClientError`
- **`src/spotify/fetch.py`** — read ops (playlists, tracks, audio/artist features, recently played)
- **`src/spotify/write.py`** — `SpotifyActions`: create playlist, add tracks
- **`src/etl/loader.py`** — Polars-based data loading with Parquet caching
- **`src/etl/db.py`** — DuckDB connection + schema DDL
- **`src/etl/bootstrap.py`** — one-time load from archived CSVs into DuckDB
- **`src/etl/sync.py`** — live Spotify → DuckDB sync
- **`src/mcp_server/server.py`** — FastMCP tools exposed to the LangGraph agent
- **`src/agent/`** — Empty; LangGraph nodes (intent, analysis, action, synthesize) to be implemented

### Data flow

```
Spotify API → httpx (SpotifyClient) → Pydantic models → Polars DataFrames → Parquet cache
                          ↓
              MCP tools (FastMCP) → LangGraph agent → Chainlit UI
                          ↓
              ChromaDB + Wikipedia RAG
```

### Infrastructure

```
infrastructure/
  containers/
    Dockerfile             # app image
    docker-compose.yml     # Chainlit + MCP + optional Jaeger/Postgres
```

## Environment

Copy `.env.example` to `.env` and populate:
- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI`, `SPOTIFY_USER_ID`
- `ANTHROPIC_API_KEY`
- OAuth token cached at `.spotify_cache` (gitignored)

## Tests

```
tests/
  unit/         ← fast, no external deps (40 tests)
  integration/  ← skipped unless SPOTIFY_CLIENT_ID is set
```

## Development Phases

- **Phase 1** ✓ — structlog, Pydantic v2 schemas, Polars loader
- **Phase 1.5** ✓ — custom Spotify OAuth (httpx), exception hierarchy, infra layout, test split
- **Phase 2** ✓ — Deleted legacy `src/data/analysis/` and `src/data/models/` (pandas + hardcoded paths); cleaned `const.py`; similarity/clustering to be rebuilt in Phase 3 against DuckDB
- **Phase 3** — Implement LangGraph agent (state schema, nodes, routing) ← next
- **Phase 4** — Wire MCP tools; Wikipedia RAG
- **Phase 5** — Connect Chainlit → agent
