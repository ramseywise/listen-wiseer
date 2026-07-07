# Changelog

## Phase 8 — RAG right-sizing + agentic web search (2026-07-07)

Plan: `.claude/docs/plans/phase8-rag-rightsize-agentic-search.md`

- Fixed dev environment: stale `.venv` (path pointed at a moved-from location), unpinned Python resolving to an incompatible interpreter (`gensim` build failure), and `deepeval` telemetry hanging test collection. Added `.python-version` and `DEEPEVAL_TELEMETRY_OPT_OUT=YES` (Makefile-exported).
- Deleted `rag_core/` — an unfinished retrofit of a Danish support-bot RAG (OpenSearch/e5-large lineage), plus orphaned eval scaffolding in `evals/` that shared the same lineage (`run_local_eval.py`, `metrics/retrieval_eval.py`, `tasks/{extract_golden,generate_synthetic,tracing}.py`, dead classes in `tasks/models.py`) and `tests/unit/rag/`. Moved the one music-relevant, load-bearing piece (`QueryAnalyzer` intent classifier) to `agent/intent.py`.
- Split `agent/nodes.py` (651 lines) into `agent/graph_nodes.py`, `agent/memory_helpers.py`, `agent/validation.py`, `agent/response.py`.
- Rewrote `agent/tools/web_search.py`: query decomposition + parallel Tavily fan-out for complex questions, `search_depth="advanced"`, LLM synthesis with citations, and a confidence gate (high/medium/low based on what Tavily actually returned) modeled on playground's `lg_agent` CRAG pattern. Wired the confidence tier into `validate_tool_output`'s corrective-retry check and citations into `format_response`'s `agent_response.sources`.
- Updated `CLAUDE.md`/`README.md` throughout to remove stale rag_core framing.
- Added test coverage that didn't exist before: `tests/unit/agent/test_web_search.py` (13 tests), `tests/unit/agent/test_validation.py` (5 tests, confidence-gate specific).
- Unit suite: 443 passed/3 skipped/0 failed baseline → 461/3/0 after new tests. No regressions.

### Review pass (`.claude/docs/reviews/phase8-rag-rightsize-agentic-search.md`)

- **Fixed a real bug found in review**: `format_response`'s source-citation loop had no turn boundary and could leak a prior turn's web-search citations into an unrelated current answer. Fixed by stopping the backward walk at the most recent `HumanMessage`. Regression test added (`test_response.py`, 6 new tests).
- 5 minor findings noted but not fixed (efficiency/simplification nits in `web_search.py`, one artifact-shape coupling note in `validation.py`) — see review doc.
- Unit suite after fix: **467 passed, 3 skipped, 0 failed**.

**Follow-up not done this session** (needs live credentials/services): manual HITL test of the playlist-write `interrupt()` flow through Chainlit, `make eval-unit`/`eval-trajectory`/`eval-e2e`, `make infra-smoke`.
