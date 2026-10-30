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

## Phase 9 — Free music stack, off Spotify (2026-10-28 → 10-30)

Plan: `.claude/docs/archive/plans/2026-10-28-free-music-stack.md`

- **S0** cleanup: 23 completed plan docs archived.
- **S1** `src/sources/` adapter layer — MusicBrainz, Deezer, Last.fm, ListenBrainz (CF + LB Radio), YouTube; shared httpx client with per-host rate limit and 429/503 retry; `httpx.MockTransport` tests.
- **S2** `etl/history.py` (Spotify privacy export → `plays`), `etl/resolve.py` (→ `track_xref`, MBID canonical, resumable); `make import-history`, `make resolve-ids`. Dropped dead `rag_chunks`.
- **S3a** `recommend/discover.py` open-world discovery: candidates from Last.fm / LB Radio / LB CF / Deezer, scored on source agreement + match + artist support − log1p(plays). S3b learned reranker data-gated → carried into the repo audit (phase F).
- **S4** playback: `library/{playlists,playback}.py`, `local_playlists` + `playable_cache`, tools `discover_tracks`, `play_track`, `save_playlist` (HITL, JSPF export), `list_playlists`; Chainlit play/save actions + inline 30s Deezer preview. Fixed `get_connection` deleting a valid DB on any IOException.
- **S5** agent/MCP swap: history from local `plays`, `recommend_*` take names, `user_id` setting (alias `SPOTIFY_USER_ID`). Deleted `src/spotify/`, Spotify tools/tests, `make auth`.
- **S6** legal downloads: `sources/{archive_org,jamendo}.py`, `library/downloads.py` + `library` table, ID3/MBID tagging, `find_free_downloads` / `download_track`, Navidrome (`make navidrome`).
- **S7** evals: new `listen` intent, golden set 55 → 61, baseline re-cut; guard test that every mapped/golden tool exists. Tier 2/3 not re-run.

## Repo audit — fresh clone + production readiness (2026-10-30)

Plan: `.claude/docs/plans/2026-10-30-repo-audit.md` · branch `repo-audit-hardening`

- **A** Fresh clone works end to end: `make train` reads active-playlist membership from DuckDB (`enoa.csv` now a legacy fallback); `etl.bootstrap` is an idempotent schema migration, CSV import only if `data/archived/` exists; new `make doctor` (`utils/doctor.py`) — keys set/unset, row counts, models, empty-`plays` warning, `--strict`; `make app` runs it first. Discovery scores are rank-normalised per source so LB Radio no longer dominates Last.fm (absolute scores changed scale).
- **B** Docs/config caught up with Phase 9: `.env.example`, `setup.sh`, README, CLAUDE.md, this file. Deleted `ttd.md`, `.deepeval/`, `.spotify_cache/`, `evals/{metrics,trials}` stubs, `notebooks/00_test_functions.ipynb`.
- **C** Dependency diet: dropped yellowbrick, aiohttp, rich, click, pyyaml, langchain-community; scipy + imbalanced-learn → dev group (notebooks); duplicate `[project.optional-dependencies] dev` removed. `sentence-transformers` + torch moved to the `embeddings` extra (CPU-only torch index on Linux); without it memory search is unranked. pyright 53 → 0 errors in `src/`, gated in `make lint` and CI. Runtime `HeuristicChecker` moved to `agent/checker.py` (src/ no longer imports evals/). New `etl.db.fetch_count`.
- **C bug fixes**: agent LLM timeout was silently ignored (now set on `ChatAnthropic`); langmem optimizer got dicts instead of `AnnotatedTrajectory`; Langfuse handler used an API removed in langfuse ≥ 3.
- **D** Coverage 77 % → 83 %; wiring modules (dependencies, graph, genre_tables, sources) at 100 %; scripted-LLM HITL `save_playlist` integration test (approve/reject) closes the Phase 8 follow-up. CI floor `--cov-fail-under=80`. 672 tests pass.
- **E** Docker: MCP server `MCP_TRANSPORT=stdio|streamable-http` (compose `mcp` at `http://localhost:8765/mcp`; logs to stderr); dead settings removed (`enable_tracing`, `jaeger_endpoint`, `similarity_method`, `audio_feature_weight`, `genre_weight`, `last_fm_id`); multi-stage images, non-root uid 1000, app 10.5 → 3.84 GB, mcp 2.61 GB; compose gets `--env-file .env`. `make infra-smoke` passes (postgres, app, mcp).
- **Left (F, data-gated)**: real `import-history` / `resolve-ids` run, ListenBrainz import, S3b LightGBM reranker, Tier 2/3 eval re-run — all wait on the Spotify extended streaming history export.
