# CLAUDE.md

## Stack

**listen-wiseer** — Spotify recommendation agent
- LLM: Claude Haiku (`claude-haiku-4-5-20251001`) · LangGraph · Chainlit · FastMCP
- Data: Polars · DuckDB · Parquet cache
- ML: GMM clustering + LightGBM reranker · scikit-learn pipelines
- RAG: ChromaDB + sentence-transformers + Wikipedia
- Auth: custom OAuth via httpx · token at `.spotify_cache`

## Commands

Run `make help` for the full list.

## Source layout

```
src/
  utils/        — config, schemas, exceptions, constants, logging
  spotify/      — OAuth, httpx client, fetch/write ops
  etl/          — DuckDB bootstrap/sync, Polars loader
  recommend/    — ML layer (GMM + LightGBM, Polars-native)
    schemas.py, train.py, engine.py, pipelines.py
    modules/: similarity, clustering, classifiers, genre (ENOA)
  mcp_server/   — 4 recommend_* tools + Spotify tools
  agent/        — LangGraph (Phase 3, in progress)
  app/          — Chainlit entry point

models/         — serialized artifacts (gitignored)
```

## Environment

`.env.example` → `.env`:
- `SPOTIFY_CLIENT_ID/SECRET/REDIRECT_URI/USER_ID`
- `ANTHROPIC_API_KEY`
