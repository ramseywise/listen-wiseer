---
name: listen-wiseer architecture and phase status
description: listen-wiseer project — phase status, key design decisions, corpus facts, open gotchas
type: project
---

Spotify music recommendation + exploration agent. LangGraph + Chainlit + FastMCP + LightGBM.

**Why:** Personal music assistant personalised to the user's own ENOA taste map — not a generic Spotify wrapper.

## Phase status (as of 2026-04-26)

| Phase | Status |
|-------|--------|
| 1–5b — full stack, OAuth, ML, agent, memory, RAG, intent routing | ✓ DONE |
| 6 — Refactor: Tavily web search, Docker chat, eval harness, clean deps | ✓ DONE |
| **7 — Music exploration rework** | **PLANNING** |

## Phase 7 direction

Reworking toward a conversational music explorer (recommendations + genre/artist exploration + personalization). Key decisions made:
- Keep LangGraph (not migrating to ADK) — state management needed for ML pipeline
- Extract Spotify client as FastMCP server (composable, Claude-native)
- Single graph with multi-node intent routing (not separate subagents yet)
- Skip music wiki for now — Tavily covers exploration well enough for prototype

## Graph topology (post-5b)

```
START → trim_history → classify_intent → [route_after_classify]
    → low confidence  → clarify_or_proceed → END (wait for user)
    → high confidence → rewrite_query (coreference-gated Haiku) → agent → [route]
        → call_tools → validate_tool_output → agent (loop)
        → END
```

## Key architectural decisions

- 595k-row corpus. Brute-force cosine ~200ms — acceptable; FAISS deferred.
- ENOA (top/left) coordinates are the differentiator: encode user's own curation patterns, not just audio similarity.
- StructuredTool wrapping (direct Python calls) over langchain-mcp-adapters — simpler, no process management.
- ChromaDB removed (Phase 6 cleanup) — Tavily replaces RAG for artist context.
- `rag_core/` left in place but suspended; wired as optional Tavily enrichment layer.
- `MemorySaver` for in-session multi-turn only — cross-session persistence deferred.
- LLM: single `_llm` (Haiku) reused for both agent and rewrite — no separate `_haiku` instance.
- `langchain-anthropic` (`ChatAnthropic`) used over raw SDK for LangFuse span visibility.

## Active gotchas

- **Git LFS blocker**: `listen_wiseer.db` via LFS — other env can't pull. Decision deferred.
- `models/` and `data/cache/` gitignored — regenerate after pull (`make train`)
- `RecommendationEngine` raises `FileNotFoundError` if pkls missing — wrap in try/except
- `audio-features` Spotify endpoint dead (403, deprecated 2025)
- Last.fm key may still be pending activation (error 10 = pending manual review, not wrong key)
- 32 test failures are all `duckdb.IOError` (missing LFS DB) — not regressions
- Full `tests/unit/` suite hangs on some later test files — use targeted runs
- **REDIS_URL** needed for cross-session memory persistence; `InMemoryStore` for dev

## ETL / data facts

- `data/listen_wiseer.db`: 2182 tracks, 291 genre mappings, 2182 enriched profiles
- `artists` table has `artist_name` column — populated from playlist CSVs; 1456 names
- `audio_features.features_source` — `'spotify'` for all 2182 bootstrap rows
- `genre_xy` table: 6291 ENOA genres with top/left/color
- Cron: `~/Library/LaunchAgents/com.wiseer.listen-wiseer-sync.plist` registered, daily 02:00

## How to apply

Next session: write Phase 7 research doc (`research/music-agent/exploration-architecture.md`) covering Spotify MCP server design, graph refactor plan, and exploration UX. Then plan and execute.
