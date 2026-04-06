# SESSION.md — listen-wiseer

## Active docs

- **Plan**: `.claude/docs/plans/phase5b_intent.md` (DONE)
- **Research**: `.claude/docs/research/eval-harness.md`
- **Research (prior)**: `.claude/docs/research/infra_support.md`

## Current position

- **Phases 3a–3d**: DONE (ML pipeline, EDA notebooks)
- **Phase 4a** (LangGraph agent + Chainlit): DONE
- **Phase 4b** (memory): DONE — episodic, taste, procedural memory
- **Phase 5a** (RAG core adaptation): DONE — DuckDB vector store, MiniLM embedder, Wikipedia/Tavily fetchers, MusicRAG orchestrator, 93 RAG tests passing
- **Phase 5b** (intent routing): DONE — all 6 steps complete (Step 6 smoke deferred to local manual testing)
- **Phase 5c** (eval harness): UP NEXT — LangFuse tracing, golden dataset, intent/tool metrics
- **Phase 6a** (testing): PLANNED — Playwright MCP for UI smoke tests, screenshot-based visual regression, Chainlit UX validation
- **Phase 6b** (dashboard): PLANNED — observability dashboard, metrics visualization, eval results display
- **Last updated**: 2026-04-06

## Phase 5b summary

Graph topology after 5b:
```
START → trim_history → classify_intent → [route_after_classify]
    → low confidence  → clarify_or_proceed → END (wait for user)
    → high confidence → rewrite_query (coreference-gated Haiku) → agent → [route]
        → call_tools → validate_tool_output → agent (loop)
        → END
```

Key additions:
- Music-domain query understanding (5 intents, entity extraction, synonym expansion)
- Intent confidence routing with clarification node
- Coreference-gated query rewriting (Haiku LLM, space-padded signals)
- Post-tool output validation (empty/error, intent-tool alignment, entity coverage, 1-retry cap)
- `get_related_artists` tool (10 tools total)
- 97 tests passing across agent/rag/spotify suites

## Phase 5b plan review decisions (2026-04-06)

Key decisions from plan review:
- **Clarification re-trigger**: No bypass — trust user phrasing after clarification
- **LLM instance**: Single `_llm` (Haiku) reused for both agent and rewrite — no separate `_haiku`
- **INTENT_MAP bridge**: Clean up in Step 1 when intent strings change
- **AgentState fields**: All accessed via `.get()` with defaults — existing tests unaffected
- **_ERROR_SIGNALS**: Bare `"error"` removed — too broad for heuristic matching
- **_COREFERENCE_SIGNALS**: Space-padded to avoid matching inside words
- **SpotifyClientError**: Lazy import in `_get_related_artists` matching `_search_tracks` pattern

## Token log

| Date | Start | End | Turns | Compacted? |
|------|-------|-----|-------|------------|
| 2026-04-02 | — | — | — | yes |
| 2026-04-03 | — | — | — | no |
| 2026-04-04 | — | — | — | yes |
| 2026-04-05 | — | — | — | yes (x5) |
| 2026-04-06 | — | — | — | yes (x3) |

## Active gotchas

- **Git LFS blocker**: `listen_wiseer.db` via LFS — other env can't pull. Decision deferred.
- `models/` and `data/cache/` gitignored — regenerate after pull (Track2Vec then `make train`)
- `RecommendationEngine` raises `FileNotFoundError` if pkls missing — wrap in try/except
- `audio-features` Spotify endpoint dead (403, deprecated 2025)
- Last.fm key pending activation
- 32 test failures are all `duckdb.IOError` (missing LFS DB) — not regressions
- Full `tests/unit/` suite hangs on some later test files — use targeted runs

## Open questions / blockers

- **Git LFS / DB portability** — install lfs on other env vs. object storage
- **Last.fm key** — pending activation
- **REDIS_URL** — needed for cross-session memory persistence; `InMemoryStore` for dev

## Next session prompt

```
We're in listen-wiseer, starting Phase 5c (Eval Harness).
Phase 5b (Intent Routing) is complete — see PR and `.claude/docs/plans/phase5b_intent.md`.

Branch: main (after 5b merge)

Phase 5c goals:
- LangFuse/LangSmith tracing integration for full graph observability
- Store successful conversations as golden eval examples
- Eval harness to replay golden examples and measure quality
- Intent classification accuracy metrics
- Tool routing precision tracking

Key context for 5c:
- Graph has 7 nodes: trim_history → classify_intent → rewrite_query → agent → call_tools → validate_tool_output (loop)
- Intent classification is keyword-based (no LLM) — eval will determine if upgrade needed
- Confidence threshold (0.4) and max_retries (1) are configurable — eval data will tune these
- 10 tools total, intent-tool alignment already tracked in validate_tool_output

Start with: /research eval-harness
```
