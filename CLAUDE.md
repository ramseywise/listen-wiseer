# CLAUDE.md — listen-wiseer

## Project Stack

**listen-wiseer** — Spotify recommendation agent
- LLM: Claude Haiku (`claude-haiku-4-5-20251001`) · LangGraph · Chainlit · FastMCP
- Data: Polars · DuckDB · Parquet cache
- ML: GMM clustering + LightGBM reranker · scikit-learn pipelines
- Context: agentic Tavily web search for artist/genre history (query decompose/fan-out + confidence gating; see Phase 8 plan)
- Auth: custom OAuth via httpx · token at `.spotify_cache`

## Refs (read before writing code here)

- `~/.claude/refs/python.md`, `logging.md`, `ml.md`, `langgraph.md`

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
  agent/        — LangGraph agent + Chainlit app
    graph.py, graph_nodes.py, memory_helpers.py, validation.py, response.py,
    state.py, memory_store.py, intent.py, tools/
  app/          — Chainlit entry point

models/         — serialized artifacts (gitignored)
.mcp.json       — Claude Code MCP server registration
```

## Phase status

| Phase | Status |
|-------|--------|
| 1–2 — stack, OAuth, GMM/LightGBM, 8 MCP tools | ✓ DONE |
| 3a–3d — ETL hardening, feature engineering, EDA | ✓ DONE |
| 4a — LangGraph agent + Chainlit | ✓ DONE |
| 4b — episodic, taste, procedural memory | ✓ DONE |
| 5a — RAG core (DuckDB vector, MiniLM, Wikipedia, 93 tests) | ✓ DONE |
| 5b — Intent routing (5 intents, clarify node, 10 tools, 97 tests) | ✓ DONE |
| 6 — Refactor: Tavily web search, clean deps, Docker chat, eval harness | ✓ DONE |
| 7a — Exploration tools: 6 fetch functions, 7 new tools, MCP parity | ✓ DONE |
| 7b — Intent taxonomy (explore_my_taste + discover), Chainlit suggestion chips | ✓ DONE |
| 7c — Genre lineage tool, taste drift analysis, Postgres memory store | ✓ DONE |
| 8 — RAG right-sizing (deleted `rag_core/`), agentic web search, HITL/eval hardening | ✓ DONE |

## Active gotchas

- `listen_wiseer.db` via Git LFS — other environments can't pull; run `make init-db && make train` on first clone
- `models/` and `data/cache/` gitignored — regenerate after pull (`make train`)
- `audio-features` Spotify endpoint dead (403, deprecated 2025) — ENOA genre embeddings in use; Last.fm activation pending
- Last.fm error 10 = pending manual activation (not wrong key) — just wait
- `pyproject.toml` pins `requires-python = ">=3.11"` with no upper bound — `uv sync` on a newer default interpreter (3.13+) will pick it and fail to build `gensim` (Cython uses removed CPython internals). A committed `.python-version` (3.11) pins this; don't remove it.
- `deepeval`'s pytest plugin pings telemetry on import — hangs for minutes in restricted-network environments. `make test*` targets export `DEEPEVAL_TELEMETRY_OPT_OUT=YES`; set it yourself if running `pytest` directly.
- `rag_core/` deleted (Phase 8) — was an unfinished retrofit of a Danish support-bot RAG (OpenSearch/e5-large lineage), never fully adapted to music. Web/artist/genre context is Tavily-only now (`get_artist_context_tool`, `get_genre_context_tool`); set `TAVILY_API_KEY`. Intent classification (`QueryAnalyzer`) moved to `agent/intent.py` — it was the one music-relevant piece.
- `InMemoryStore` used for cross-session memory in dev; Redis/Postgres for prod (Phase 6 Phase 3)
- Playback scopes (`user-read-playback-state`, `user-modify-playback-state`, `user-read-currently-playing`) added — existing `.spotify_cache` must be deleted and re-authed (`rm .spotify_cache && make auth`) to pick up new scopes

## Environment

Copy `.env.example` → `.env` and fill in:
- `SPOTIFY_CLIENT_ID/SECRET/REDIRECT_URI/USER_ID`
- `ANTHROPIC_API_KEY`
- `TAVILY_API_KEY` — required for artist/genre context tool

---

## Developer Identity

Python/AI engineer building LLM-powered applications. Comfortable with async Python,
LLM orchestration (LangGraph), Polars, DuckDB, structlog. Skip basics unless asked.

## Communication

- Brief and direct. Lead with the action.
- No filler, no trailing summaries of what you just did.
- File:line references over prose descriptions.
- Don't add unsolicited comments, docstrings, or refactors to code I didn't ask to change.

---

---

## Memory Taxonomy

Memory files live in `~/.claude/projects/-repo/memory/`. Each file uses frontmatter `type:` (one of the four below) plus a `subtype:` field and filename that narrows it further.

| `type:` | `subtype:` values | When to use |
|---|---|---|
| `user` | — | Role, expertise, preferences that shape how to communicate |
| `feedback` | `preference` · `pattern` | `preference`: style/tool choices; `pattern`: recurring corrections |
| `project` | `decision` · `milestone` · `problem` | Locked choices, completed phases, known blockers |
| `reference` | — | Where to find things in external systems |

**Filename convention**: `<type>_<subtype>_<topic>.md` — e.g. `feedback_pattern_no_trailing_summaries.md`, `project_decision_auth_middleware.md`.

Hard rules are in `.claude/rules/hard-rules.md` (auto-loaded — not repeated here).

---

## Workflow

Non-trivial tasks follow phases:

| Phase | Command | Artifact |
|-------|---------|----------|
| 1. Research | `/research <slug>` | `## Research` in `.claude/docs/plans/YYYY-MM-DD-<slug>.md` |
| 2. Plan | `/plan <slug>` | `## Plan` in the same doc |
| 2.5. Plan Review | `/plan review` | plan section (iterated) |
| 3. Execute | `/execute` | `.claude/docs/CHANGELOG.md` |
| 4. Review | `/code-review <slug>` | `## Review` in the same doc + PR |

One doc per work item in `.claude/docs/plans/` (gitignored), with a `Status:` line — no SESSION.md. Only `CLAUDE.md` lives at the project root.

### Tooling

- `uv run pytest tests/unit/` — unit only (fast, no external deps)
- `.env` never committed; `.env.example` is the template

### Hook-enforced standards

All standards below are enforced via `settings.json` hooks — do not run manually.

**PostToolUse (Write|Edit):**
- ruff format + check on every `.py` write
- pyright type check (pyrightconfig-aware, advisory)
- `[no-print]` no `print()` in `src/` — use structlog
- `[bare-except]` no bare `except:` — catch specific exceptions
- `[use-structlog]` no stdlib `logging` — use structlog
- `[use-polars]` no pandas — use polars
- `[mutable-default]` no `def f(x=[])` — use `None` sentinel
- `[sdk-factory]` no bare `anthropic.Anthropic/AsyncAnthropic()` outside `utils/client.py`
- `[sdk-model]` no hardcoded `claude-*` model strings — use settings
- Test coverage warning on untested public functions
- File size warning at >400 lines
- Phase artifact writes trigger compact reminder on next prompt

**PostToolUse (Bash):** Failed commands → `.claude/friction-log.jsonl` · long test runs → desktop notification

**PreToolUse (Write|Edit):** Review gate (show before/after, confirm via `touch .claude/.edit_ok`) · secrets scan

**PreToolUse (Bash):** `git commit` blocked if tests fail · `git commit` blocked if `uv.lock` out of sync · `pip install` blocked · destructive commands blocked

### Path convention

`src/paths.py` defines `REPO_ROOT`, `DB_PATH`, `DATA_DIR` — all notebooks and scripts import from there.

### TODO annotations

- `TODO(0)` — critical; do not merge
- `TODO(1)` — high (architecture, major bugs)
- `TODO(2)` — medium (bugs, missing features)
- `TODO(3)` — low (polish, tests, docs)
- `TODO(4)` — open questions / investigations
- `PERF` — performance follow-ups

### Issue tracking

Branch: `feature/lin-{id}-{slug}` | Commit: `{type}: {desc} (LIN-{id})` | PR: `LIN-{id} {description}`
