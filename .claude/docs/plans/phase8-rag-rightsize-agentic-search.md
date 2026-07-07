# Phase 8 — RAG Right-Sizing + Agentic Web Search

**Status:** EXECUTED (2026-07-07) — see Execution Notes below
**Depends on:** Phase 7c ✓
**Scope:** ~1-2 days

---

## Execution Notes (2026-07-07)

All phases executed in one session. Deviations from the plan as written:

- **Phase 1 scope grew.** The usage audit during execution found the Danish-support-bot lineage wasn't confined to `rag_core/` — it had leaked into `evals/` too: `evals/run_local_eval.py` (imported `retrieval.client.OpenSearchClient` — the *original*, never-even-DuckDB-adapted client), `evals/metrics/retrieval_eval.py`, `evals/tasks/{extract_golden,generate_synthetic,tracing}.py`, and dead `GoldenSample`/`RetrievalMetrics`/`EvalRunConfig` classes in `evals/tasks/models.py` (one had `language: str = "da"` and `source_ticket_id` fields — unambiguously not music). All deleted alongside `rag_core/` and `tests/unit/rag/`; confirmed zero live references first.
- **Phase 0's nodes.py split happened after Phase 1's intent-module move**, not before, since `graph_nodes.py` needed to import from the already-relocated `agent/intent.py`.
- **Two extra fixes surfaced and got folded into Phase 0**, both blocking any test run before this session, neither previously diagnosed:
  1. `pyproject.toml`'s `requires-python = ">=3.11"` had no upper bound — `uv sync` picked the system Python (3.14.4) and `gensim` failed to compile (`ma_version_tag` removed from CPython internals post-3.11). Fixed with a committed `.python-version` pinning 3.11.
  2. `deepeval`'s pytest plugin pings telemetry on import/collection — hangs 15+ minutes in this sandboxed environment instead of failing fast. Fixed via `DEEPEVAL_TELEMETRY_OPT_OUT=YES`, exported globally in the `Makefile` and documented in `.env.example`.
- **Confidence gate came in simpler than drafted**: 3 tiers (high/medium/low) instead of 4 — Wikipedia-fallback-success collapses into "medium" rather than a separate "medium-low," since the distinction added no behavioral difference (only `confidence == "low"` — meaning literally no text found anywhere — triggers the honest non-answer path, which happens naturally rather than needing a separate check).
- **Synthesis LLM call is sync** (`_llm.invoke`, `ThreadPoolExecutor` for fan-out), not async as originally sketched — every other tool in `agent/tools/` is sync (`StructuredTool.from_function` with a plain `func`), and LangGraph's `ToolNode` runs sync tools fine under `.ainvoke()`. Introducing the repo's first async tool wasn't justified by this change.
- **Citations wired end-to-end**: `web_search.py` returns `(content, artifact)` via `response_format="content_and_artifact"` → `agent/validation.py` reads `artifact["confidence"]` to gate corrective retries → `agent/response.py` reads `artifact["sources"]` into `agent_response.sources`. New `AgentState.agent_response` includes `sources` alongside the existing `message`/`track_list`/`suggestions`.
- **Test coverage added, not just preserved**: `web_search.py` had zero tests before this session (now 13, ~86% coverage); new `tests/unit/agent/test_validation.py` covers the confidence-gate wiring specifically (didn't exist before either). Also simplified `tests/unit/agent/test_nodes.py`'s episodic/memory-stats tests to import the real `agent.memory_helpers` functions instead of a hand-maintained replica, now that module has no DuckDB dependency.
- Full unit suite: 461 passed, 3 skipped, 0 failed before the review pass (was 443/3/0 pre-session — no regressions, `+18` new tests).
- **Review pass** (`.claude/docs/reviews/phase8-rag-rightsize-agentic-search.md`, medium effort, 8 finder angles): found and fixed one real bug — `format_response`'s source-citation loop had no turn boundary and could leak a prior turn's citations into an unrelated answer. Fixed + regression-tested (`test_response.py`, 6 tests). 5 minor findings noted, not fixed (see review doc). Final unit suite: **467 passed, 3 skipped, 0 failed**.

**Not done in this session (flagged for you to run manually, per Phase 3 below):**
- Manual end-to-end test of the `interrupt()`-based playlist-write HITL through Chainlit — needs a live `ANTHROPIC_API_KEY`/`SPOTIFY_*`/browser session, can't be exercised headlessly.
- `make eval-unit`/`eval-trajectory`/`eval-e2e` — cost money (Tier 2/3) or need `ANTHROPIC_API_KEY` (all tiers); not run in this session.
- `make infra-smoke` — needs Docker stack running.

---

## Goal

Four things, in order:
1. Make the dev environment actually work (it currently doesn't, for two separate reasons).
2. Delete everything in `rag_core/` that's lineage from the old Danish support-bot project (OpenSearch/e5-large-era retrieval, generation, storage, orchestration) — none of it was ever finished being adapted to music, none of it is music-genre-specific. Keep and relocate the one piece that *is* music-domain and load-bearing: the intent/query-understanding layer.
3. Replace the single Tavily call in `web_search.py` with an actual agentic search step (query planning + multi-source + citations) — reusing the query-understanding features that already exist but are currently discarded (`decompose_query`, `score_complexity`), rather than building new machinery. Test those features for real instead of leaving them computed-and-ignored.
4. Borrow two specific patterns from playground's `lg_agent` (its CRAG-style graph) worth testing here: confidence-gated generation (don't answer confidently on weak search results) and structured source citations. Note what's HITL already vs. what would be new.

---

## Current state (verified this session, not assumed from docs)

### Environment was broken two ways
1. `.venv` shebangs pointed at `/Users/ramsey.wise/Workspace/listen-wiseer/.venv/...` — stale path from before the repo moved to `/Volumes/INTENSO`. Fixed by `rm -rf .venv && uv sync --group dev`.
2. `pyproject.toml` pins `requires-python = ">=3.11"` with no upper bound. `uv` resolved the system default (3.14.4) and `gensim==4.4.0`'s Cython extension fails to compile against it (`PyDictObject.ma_version_tag` was removed from CPython internals post-3.11). **`make train` / anything importing `src/recommend/preprocessing.py` was unbuildable on a fresh machine, full stop** — this is likely the actual reason testing has stalled repeatedly, not just the venv path. Fixed by `uv python pin 3.11` + rebuild. **Action: commit the `.python-version` file** so this doesn't recur on the next clone or teammate machine.

### `rag_core/` usage audit
Only one file is imported by anything live: `rag_core/orchestration/query_understanding.py` → `agent/nodes.py:16` (`QueryAnalyzer`, used for intent classification — pure keyword matching, no LLM, no vector search involved).

Everything else has zero references outside its own file:
- `orchestration/{graph.py, music_rag.py, router.py}`
- `retrieval/` (duckdb_client, embedder, reranker, scoring)
- `generation/generator.py`
- `preprocessing/` (fetchers, chunker, parsing, pipeline)
- `storage/` (metadata_db, snippet_db)

Separately, `agent/tools/web_search.py::_query_rag_chunks()` does a **raw SQL** `SELECT ... FROM rag_chunks` — it doesn't go through `rag_core` at all, and the table is empty (no ingestion pipeline has ever run against it in this environment), so that branch is permanently a no-op today.

Origin: per `.claude/docs/plans/phase5a_rag.md`, `rag_core/` was forked from a **Danish customer-support-assistant RAG** (OpenSearch + e5-large) and retrofitted for music (DuckDB vss + MiniLM). It was never fully wired up as music RAG before Phase 6 suspended it in favor of Tavily. So this isn't "a feature we're pausing" — it's a retrofit that never finished, then got frozen.

### `web_search.py` today
`get_artist_context_tool` / `get_genre_context_tool`: one `TavilyClient.search(search_depth="basic", max_results=3, include_answer=True)` call → Wikipedia page-summary fallback if no Tavily key/answer → dead `rag_chunks` enrichment check. No query planning, no multi-hop, no source URLs surfaced back to the agent or user (the agent can't cite anything), broad `except Exception` around the Wikipedia fallback path.

### Other findings folded into this plan
- `CLAUDE.md`'s "Source layout" section lists `agent/rag/` and `agent/intent/` subpackages that don't exist — the real layout is flat (`memory_store.py`, `tools/`).
- `agent/nodes.py` is 651 lines, over the repo's own 400-line file-size hook warning — mixes graph nodes, episodic/procedural memory helpers, tool-output validation, and response formatting.
- `QueryAnalyzer.analyze()` computes `expanded_query` and `retrieval_mode` (`snippet`/`hybrid`/`dense`) — both dead, `nodes.py` only reads `intent`, `confidence`, `entities`, `sub_queries`. `decompose_query()` (multi-hop query splitting) is computed into `sub_queries` and passed through as `query_variants` but nothing currently consumes it either — this is actually useful raw material for Phase 2 below, not just dead code.
- Playground's `rag_agent` (a real doc-RAG: 50 curated articles, sentence-transformer embeddings, cross-encoder reranker, citation guardrails, dedicated eval graders) is the right reference for what a *justified* doc-RAG looks like — the gap is the curated, maintained corpus, not the code. Not worth rebuilding here without that investment.
- listen-wiseer already has **real HITL**, not just prompt-level confirmation: `agent/tools/spotify_write.py` uses `langgraph.types.interrupt()` for playlist creation, and `app/main.py` resumes from it. This was flagged as "planned" in the old Phase 6 plan but is actually done — corrected here. It has not been exercised end-to-end since the environment was broken; Phase 3 adds a manual test for it.

### Playground `lg_agent` (CRAG) pattern — what's actually worth borrowing
Read `playground/src/agents/lg_agent/graph/builder.py` + `nodes/{retrieve,generate}.py`. Their "CRAG" graph is `memory_load → guardrail → retrieve → generate`, not a corrective retry loop in production (the loop version — `ConfidenceSignal.should_continue_crag()` in `rag_agent/confidence.py` — is defined but also unused in the wired graph; same "computed and discarded" smell we have with `decompose_query`). The part that **is** live and worth copying:
- `generate_node` checks `confidence_score < _LOW_CONF and not docs` → returns an honest "couldn't find relevant information" message instead of asking the LLM to answer anyway. Confidence comes from the retrieval step, not a vibe.
- `AssistantResponse` carries a structured `sources: list[{title, url}]` field, populated by `_extract_sources()` from doc metadata, independent of whether the LLM remembered to cite inline.
- Guardrail node can short-circuit the graph to a `blocked` terminal state with `contact_support=True` — their equivalent of "escalate to a human" for a system with no in-graph interrupt.

Mapped onto listen-wiseer (no vector store, so no rerank score) — the equivalent confidence ladder comes from **what Tavily actually returned**: direct `answer` field present → high; only raw `results` → medium; fell through to Wikipedia → medium-low; nothing found → low. This is Phase 2 item 6 below.

---

## Phase 0 — Stabilize (blocking, do first)

- [x] Commit `.python-version` (3.11) so `uv sync` can't silently pick an incompatible interpreter again.
- [x] Run `make test-unit` on the fixed venv, record the real pass/fail baseline. The "32 failures = missing LFS db" claim was **stale** — real baseline is 443 passed/3 skipped/0 failed (before this session's new tests; 461/3/0 after).
- [x] Fix `CLAUDE.md` Source Layout section to match reality (no `agent/rag/`, no `agent/intent/` — well, `agent/intent.py` now genuinely exists, just not as a subpackage).
- [x] Split `agent/nodes.py`:
  - `agent/graph_nodes.py` — trim_history, classify_intent_node, rewrite_query, clarify_or_proceed, agent_node, routing functions
  - `agent/memory_helpers.py` — episodic recall/store, procedural prompt injection, memory stats
  - `agent/validation.py` — validate_tool_output + `TOOL_INTENT_MAP` + `ERROR_SIGNALS`
  - `agent/response.py` — format_response, `_TRACK_LINE_RE`, `_SUGGESTION_TEMPLATES`

## Phase 1 — Delete dead RAG machinery

- [x] Move `query_understanding.py` out of `rag_core/` entirely — new home: `agent/intent.py`. Updated all 3 importers (`agent/graph_nodes.py`, `evals/agent/intent_eval.py`, `tests/unit/agent/test_intent_routing.py`).
- [x] Delete `rag_core/` in full, **plus** the orphaned Danish-support-bot eval scaffolding found during the audit: `evals/run_local_eval.py`, `evals/metrics/retrieval_eval.py`, `evals/tasks/{extract_golden,generate_synthetic,tracing}.py`, dead classes in `evals/tasks/models.py`, and `tests/unit/rag/` (14 test files).
- [x] Delete `_query_rag_chunks()` and the "Additional context" branch from `web_search.py` — done as part of the Phase 2 rewrite.
- [x] Drop the `rag_chunks` table from the DuckDB schema.
- [x] Update `CLAUDE.md` and `README.md` rag_core framing throughout (stack table, architecture diagram, project structure tree, DB table list, architectural-choices rationale).

## Phase 2 — Agentic web search

- [x] **Reuse existing complexity/decomposition.** `score_complexity()`/`decompose_query()` now actually drive fan-out in `_agentic_search()` for `complex`/multi-sub-query cases.
- [x] **Bumped Tavily to `search_depth="advanced"`.**
- [x] **Citations surfaced** via `response_format="content_and_artifact"` — `{"sources": [...], "confidence": tier}` flows from the tool through `ToolMessage.artifact` into `agent_response.sources`.
- [x] **Synthesis for multi-source fan-out** — sync `_llm.invoke()` call (not async — see Execution Notes on why).
- [x] **Confidence gate** — 3 tiers (high/medium/low; see Execution Notes for why not 4), wired into `agent/validation.py`'s `validate_tool_output` alongside the existing string-based `ERROR_SIGNALS` check.
- [x] **Structured sources** returned from the tool and threaded to `format_response`.
- [x] **HITL** — left alone as recommended; existing `create_playlist` interrupt is untouched. Flagged for manual test in Phase 3 (not run this session — needs live credentials).
- Not done: adding a second search provider (Exa/Brave) — correctly out of scope per the plan; revisit only if faithfulness evals show gaps.

## Phase 3 — Readiness checklist before real testing/dogfooding

- [x] `make test-unit` green — 467 passed, 3 skipped, 0 failed (after review-pass fix).
- [ ] `make eval-unit` (Tier 1) — **not run this session**, needs `ANTHROPIC_API_KEY`. Run before trusting intent-routing didn't regress from the `agent/intent.py` move.
- [ ] `make eval-trajectory` + `make eval-e2e` (Tier 2/3) — **not run**, cost money.
- [x] **New test cases for previously-inert features** — added `tests/unit/agent/test_web_search.py` (13 tests: confidence tiers, fan-out/synthesis, low-confidence honest-answer, Wikipedia fallback) and `tests/unit/agent/test_validation.py` (5 tests: confidence-gate wiring specifically).
- [ ] **Manually exercise the existing playlist-write HITL** through Chainlit — **not run this session**, needs a live browser/API session. Do this before considering the agent dogfood-ready.
- [ ] `.env` completeness check — not re-verified this session (no credentials available in this environment).
- [ ] `make infra-smoke` — **not run**, needs Docker.

---

## Resolved — Phase 1 scope

Decision (per plan-review feedback): **delete, don't archive.** The Danish-support-bot-lineage code (OpenSearch client patterns, e5-large embedder config, generic chunker/reranker/generator never adapted past their original domain) isn't a music portfolio artifact — it's an unfinished retrofit with zero music-specific value beyond what already got pulled into `query_understanding.py`. Archiving it under `archive/` would just relocate the same dead weight. Whatever survives should be music-genre-scoped only, matching the actual product, not generic RAG scaffolding kept "just in case."

If a real corpus-backed RAG (curated music theory/production articles, playground-`rag_agent`-style) is ever wanted, that's a **new, separate future phase** — build it clean against the current architecture, not by resurrecting this code. Not in scope here.
