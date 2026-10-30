# Repo audit — backlog completeness + local production readiness

Status: RESEARCH DONE — plan drafted, awaiting review
Branch: main (clean at audit time, `69a41f5`)

## Research

### Method (all run 2026-10-30 on this machine)

| Check | Result |
|---|---|
| `ruff check src/` + `ruff format --check` | clean |
| `uv lock --check` | in sync |
| `pytest tests/unit` | 569 passed, 3 skipped, 8s |
| `pytest tests/integration` | 19 passed |
| `pytest tests/unit --cov=src` | **77 %** line coverage (committed `coverage.xml` said 9.5 % — stale partial run from Oct 28, still lists `spotify/client.py`) |
| `pyright src` | **53 errors** |
| `evals.eval_ci` | pass, 10 metrics within baseline |
| `chainlit run --headless` | HTTP 200 after 6s; logs `agent.tools.engine_unavailable` (no models) |
| `make train` | **FAILS** — `FileNotFoundError: data/archived/enoa.csv` |
| Live sources | MusicBrainz 5, Deezer 1, Last.fm 20, LB Radio 45, Archive.org 10, YouTube 1 → all OK. Jamendo client_id valid (`status: success`) |
| Keys in `.env` | anthropic, tavily, lastfm, listenbrainz (token+user), youtube, jamendo all set; postgres/memory_store/langfuse unset |
| DuckDB rows | archive tables populated (tracks 2182, playlists 80, faves 1522, genre_xy 6291); `plays` 0, `track_xref` 0, `local_playlists` 0; no `library` table in committed DB (created lazily by `init_schema`) |
| `git lfs ls-files` | DB is in LFS (3 versions); `git-lfs` installed here |

### 1. Backlog — what is actually left

Every phase 1–9 is done except the items below. No GitHub issues or open PRs exist; the backlog lives only in the plan doc.

**Code backlog (small):**
- **S3b learned reranker** — data-gated. `plays` and `track_xref` are empty because the Spotify extended streaming history has not landed. Also the known ranking bug: LB Radio match is positional (1 − i/n) vs Last.fm absolute similarity, so LB dominates `discover.py` scores. Rank-normalising per source does *not* need the export and could be done now.
- **Tier 2/3 evals** (`make eval-trajectory`, `make eval-e2e`) not re-run since the S7 intent changes. Costs API spend.
- **Phase 8 follow-up never closed**: manual HITL test of `save_playlist` interrupt through Chainlit; `make infra-smoke` never run.
- **Jamendo** — plan says "untested live". Verified today: client_id works. Only the plan doc is stale.

**User-side blockers (not code):**
1. Spotify → Privacy → request Extended streaming history → drop JSON in `data/listening_history/` → `make import-history && make resolve-ids`.
2. Import that same export into ListenBrainz so `cf_recommendations` stops returning empty.

**Documentation drift (the real "content" gap):**
- `.claude/docs/plans/2026-10-28-free-music-stack.md` Status line stale (says S6 Jamendo untested; S0–S7 effectively done bar S3b).
- `.claude/docs/README.md` lists phase 7a/7b/7c as the *active* plans — they are archived; Phase 8/9 not mentioned.
- `.claude/docs/CHANGELOG.md` ends at Phase 8; Phase 9 (S0–S7) never logged.
- `.claude/docs/ttd.md` is a Spotify-era test plan (`.spotify_cache`, `make auth`, "22 tools") — dead.
- `README.md`: table `track_ids` is actually `track_xref`; lists `library` table that the committed DB lacks; Project Structure still shows `spotify_train_data.csv`, "notebooks (gitignored)" (they are tracked), and describes `evals/tasks` + `evals/metrics` as real modules (they are empty stubs since Phase 8).
- `.env.example` is Spotify-era: has `SPOTIFY_*`, lacks `LAST_FM_API_KEY`, `LISTENBRAINZ_TOKEN/USER`, `YOUTUBE_API_KEY`, `JAMENDO_CLIENT_ID`, `USER_ID`; keeps the `DEEPEVAL_TELEMETRY_OPT_OUT` note though deepeval was removed.
- `setup.sh` tells users to fill in Spotify credentials and `mkdir data/vectorstore`.
- `pyproject.toml` description: "Intelligent Spotify music recommendation system … Wikipedia RAG".
- `CLAUDE.md` gotcha "run `make init-db && make train` on first clone" is wrong — both need `data/archived/*.csv`, which is gitignored and not on this machine. The committed DB already *is* the bootstrap; `make init-db` would need the CSVs.

### 2. Production quality — local run

**What works today:** app boots, chat agent, discovery (`discover_tracks`), playback resolution, history tools (empty data), artist/genre context (Tavily), downloads (Archive.org / Jamendo), playlists, MCP server (stdio), CI lint + unit + eval gates.

**P0 — fresh clone cannot produce models**
- `recommend/train.py` `_load_enoa()` hard-requires `data/archived/enoa.csv` (gitignored). The same data already sits in DuckDB: `enoa.csv` is `(playlist_name, id)` = `playlists ⋈ playlist_tracks` where `status = 'active'` (17 active playlists). Without it `models/gmm_corpus.pkl` etc. never exist and the four `recommend_*` tools silently drop out (`engine_unavailable` warning). Docker `db-init` (`python -m etl.bootstrap`) has the same CSV dependency.

**P1 — quality signals**
- pyright: 53 errors in `src/` (hook is advisory, so they accumulate).
- Coverage 77 % overall but the wiring is nearly untested: `agent/dependencies.py` 3 %, `etl/genre_tables.py` 14 %, `etl/bootstrap.py` 16 %, `sources/youtube.py` 18 %, `agent/graph.py` 19 %, `recommend/modules/genre.py` 23 %, `sources/listenbrainz.py` 24 %, `sources/jamendo.py` 25 %. No coverage floor in CI.
- `coverage.xml` / `htmlcov/` are gitignored but a stale copy sits in the tree — harmless, but misleading.

**P1 — Docker / infra drift**
- `docker-compose.yml` `mcp` service exposes port 8765 but `server.py` runs `mcp.run()` = stdio; the container has no client and exits. `app` is given `MCP_SERVER_HOST/PORT` it never reads (the app imports tools directly).
- Compose passes `TRACK_FEATURES_CACHE`, `GENRE_METADATA_CACHE`, `SIMILARITY_METHOD`, `AUDIO_FEATURE_WEIGHT`, `GENRE_WEIGHT`, `JAEGER_ENDPOINT`, `ENABLE_TRACING` — settings fields that no code reads (`similarity_method`, `audio_feature_weight`, `genre_weight`, `jaeger_endpoint`, `mcp_server_*`, `last_fm_id`, `enable_tracing` have 0 references in `src/`).
- Image runs `uv sync --frozen --no-dev` = full torch + catboost + gensim + jupyter-adjacent stack; no slim target.
- `make infra-smoke` has never been run (CHANGELOG Phase 8 follow-up).

**P2 — dependency hygiene**
- Declared but never imported: `yellowbrick`, `aiohttp`, `rich`, `click`, `pyyaml`, `imbalanced-learn`, `langchain-community`, `scipy` (transitive only), `pyarrow` (Polars reads parquet natively). `psycopg` is needed only via `langgraph-checkpoint-postgres`.
- `wikipedia` used only as a Tavily fallback; `sentence-transformers` (pulls torch) used only for memory-store embeddings — the libomp clash in CLAUDE.md exists purely because of this.
- `[project.optional-dependencies] dev` and `[dependency-groups] dev` duplicate each other (the latter also has `pyright`, `pytest-timeout`).
- `.pre-commit-config.yaml` pins `ruff v0.16.0` while pyproject requires `>=0.16.3`.
- Leftover dirs: `.deepeval/`, `.spotify_cache/`, `evals/{metrics,tasks,trials}` (stubs only), `notebooks/00_test_functions.ipynb`.

**P2 — Makefile**
- `import-history`, `resolve-ids` missing from `help` and `.PHONY`.
- `init-db` is documented as the first-clone step but requires gitignored CSVs.
- No single "doctor" target: nothing checks keys present, DB tables present, models present, before `make app`.

## Plan

Ordered by payoff. Each phase is one PR; A and B are small enough to do in one session.

### A — Fresh clone runs end to end (P0)
1. `recommend/train.py`: `_load_enoa()` reads `playlists ⋈ playlist_tracks WHERE status='active'` from DuckDB (same `(playlist_name, id)` shape), CSV only as fallback. Unit test with a synthetic DuckDB.
2. `etl/bootstrap.py`: when `data/archived/` is absent, run `init_schema` + `load_enoa_coordinates` only and exit 0 with a clear log line; compose `db-init` then becomes a schema migration, not a CSV import.
3. New `make doctor`: prints which keys are set (bool only), DuckDB table row counts, whether `models/*.pkl` exist, whether `plays` is empty. Wire `make app` to warn via the same check.
4. Verify: fresh `git clone` → `uv sync` → `make train` → `make app` → recommendation tools load (no `engine_unavailable`).
5. Fix the CLAUDE.md gotcha and README Quickstart/Fresh-machine sections to match.

### B — Docs and config catch up with Phase 9
1. Rewrite `.env.example` (free-source keys, drop Spotify + deepeval); update `setup.sh` next-steps; pyproject description.
2. README: table names (`track_xref`), `library` note, Project Structure (drop `spotify_train_data.csv`, evals stubs, "notebooks gitignored").
3. `.claude/docs/README.md`: current plan table (Phase 9 archived, this audit active). Append Phase 9 entry to CHANGELOG. Delete `ttd.md`. Move `2026-10-28-free-music-stack.md` to archive with S3b carried into this doc.
4. Delete `.deepeval/`, `.spotify_cache/`, `evals/{metrics,tasks,trials}` stubs, `notebooks/00_test_functions.ipynb` (confirm first).

### C — Dependency diet + type gate
1. Remove unused deps listed above; dedupe dev deps into `[dependency-groups]` only; bump pre-commit ruff to 0.16.3. `uv lock`, rerun suite.
2. Make `sentence-transformers` an optional extra (`[memory-embeddings]`) with a hashing/MiniLM-free fallback for `memory_store.py`, so the default install has no torch and the libomp gotcha disappears. Measure install size before/after.
3. Burn down pyright to 0 in `src/` (53 errors; mostly `object | Literal['']` return types from `settings`/dict access). Add `uv run pyright src` to `make lint` and CI.

### D — Test the wiring, add a floor
1. Tests for `agent/dependencies.py` (MemorySaver path, Postgres/Redis branches mocked), `agent/graph.py` (compile + route table), `etl/bootstrap.py` no-CSV path from A2, `sources/{youtube,listenbrainz,jamendo}` via `MockTransport` (same pattern as the other sources).
2. CI: `--cov-fail-under=75` now, raise to 80 after D1.
3. Add a scripted-LLM integration test for the `save_playlist` HITL interrupt → resume path (closes the Phase 8 follow-up without a manual Chainlit run).

### E — Docker stack that matches the code
1. Drop the `mcp` compose service or switch `server.py` to `mcp.run(transport="streamable-http")` behind `MCP_TRANSPORT` env; remove `MCP_SERVER_*` from `app` env.
2. Remove dead settings fields and their compose env lines (`similarity_method`, `audio_feature_weight`, `genre_weight`, `jaeger_endpoint`, `last_fm_id`, `enable_tracing`, cache paths).
3. Multi-stage Dockerfile using the slim extras from C2. Run `make infra-up && make infra-smoke` and record the result here.

### F — Data-gated backlog (after the Spotify export lands)
1. `make import-history && make resolve-ids`; import the same export to ListenBrainz.
2. S3b: rank-normalise per source in `recommend/discover.py` (can be done now, test with fixtures), then LightGBM reranker on `plays` labels (played ≥30s, not skipped).
3. Re-run `make eval-trajectory` / `make eval-e2e`, re-cut `eval_baseline.json`.

### Out of scope / deliberately not proposed
- Replacing Chainlit, LangGraph, or DuckDB — all working and tested.
- Postgres memory store in dev — InMemoryStore is adequate until multi-session use matters.
