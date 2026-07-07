# Review: Phase 8 — RAG Right-Sizing + Agentic Web Search

**Verdict:** GO (one confirmed bug found and fixed during review; remaining findings are minor, non-blocking)
**Plan:** `.claude/docs/plans/phase8-rag-rightsize-agentic-search.md`
**Scope reviewed:** full working-tree diff (`git diff HEAD`), nothing committed yet — 67 files changed, mostly deletions of dead code.

## Method

Medium-effort review: 8 parallel finder angles (line-by-line, removed-behavior audit, cross-file tracer, reuse, simplification, efficiency, altitude, CLAUDE.md conventions) against the full diff, then direct verification of each surviving candidate by re-reading the actual current file state.

## Findings

### Fixed during review

**[CONFIRMED] Stale source citations could leak across conversation turns** — `src/agent/response.py`
`format_response`'s source-extraction loop walked the *entire* message history backward with no turn boundary (only `continue`, never `break`), unlike `validate_tool_output` which explicitly stops at the first non-tool message. In a multi-turn conversation, a prior turn's `get_artist_context`/`get_genre_context` citations could attach to a completely unrelated later answer (e.g. asking "who is Aphex Twin?" then "recommend me some zouk tracks" — the zouk answer would incorrectly cite the Aphex Twin sources).
**Fix applied:** the loop now stops at the most recent `HumanMessage` (the start of the current turn). Regression test added: `tests/unit/agent/test_response.py::test_does_not_leak_sources_from_a_prior_turn`.

### Noted, not fixed (low severity / design tradeoffs)

- **`src/agent/validation.py:94`** — the confidence-gate check couples the generic, all-tools `validate_tool_output` to one tool pair's artifact shape (`{"confidence": ...}`) via untyped duck-typing. Real coupling risk if a third tool adopts `content_and_artifact` with a different shape, but this was an explicit, discussed design choice (Phase 2 plan item 6), not an accident. Worth a shared schema if a third structured-artifact tool shows up.
- **`src/agent/tools/web_search.py:111`** — `_tavily_client()` rebuilds a `TavilyClient` on every call instead of caching one. Real but negligible next to the network round-trip itself.
- **`src/agent/tools/web_search.py:119`** — `ThreadPoolExecutor` spins up even for the single-query case. Same negligible-relative-to-network-I/O caveat.
- **`src/agent/tools/web_search.py:80`** vs **`src/agent/response.py`** — two independent 5-line URL-dedup-by-seen-set implementations. Small enough that extracting a shared helper wasn't worth it for two call sites, but noted for if a third shows up.
- **`src/agent/tools/web_search.py:116`** — `score_complexity(..., entities={}, ...)` always passes an empty dict, permanently disabling that function's entity-count signal at this call site. Not a bug, just a slightly misleading call site.

### Checked, came back clean

- Removed-behavior audit: no orphaned references to anything deleted (`rag_core/`, `evals` scaffolding, `rag_chunks` table) — confirmed nothing outside the deleted code ever referenced it.
- Cross-file tracer: the two web-search tools' new `tuple[str, dict]` return shape (via `response_format="content_and_artifact"`) doesn't break any caller — no code calls `_get_artist_context`/`_get_genre_context` directly expecting a plain string.
- CLAUDE.md conventions: no violations of hook-enforced standards (no `print()`, no bare `except`, no stdlib `logging`, no hardcoded model strings, no mutable defaults) in any new/changed file.

## Test status

`DEEPEVAL_TELEMETRY_OPT_OUT=YES uv run pytest tests/unit/ -q` → **467 passed, 3 skipped, 0 failed** (baseline before this session was 443/3/0; +24 new tests: `test_web_search.py` ×13, `test_validation.py` ×5, `test_response.py` ×6).

## Not covered by this review (flagged in the plan, needs credentials/services)

- Manual end-to-end test of the playlist-write `interrupt()` HITL flow through Chainlit.
- `make eval-unit` / `eval-trajectory` / `eval-e2e`.
- `make infra-smoke`.
