# CLAUDE.md — listen-wiseer

## Project Stack

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

@.claude/rules/style.md
@.claude/rules/logging.md
@.claude/rules/ml.md

---

## Hard Rules

### Workflow discipline

- Implement one plan step at a time — do not skip ahead
- Never refactor outside the scope of the current plan step
- Always confirm before touching `pyproject.toml`, CI config, or infra files
- Never commit model weights, large data files, or notebooks with output cells
- Notebooks are for exploration only — move validated logic to `src/`

### Before any multi-file change or refactor

1. Present a numbered plan of what will be modified, created, and deleted
2. Wait for explicit user approval before making any changes
3. Never delete files, agents, skills, commands, or config — list candidates and wait for confirmation
4. If scope expands mid-task, stop and re-present the updated plan

### File paths

- All paths must be anchored to the repo root — never relative to CWD
- Use `Path(__file__).resolve().parent` or a shared `src/paths.py` that defines `REPO_ROOT`
- Apply this to DB connections, file imports, config loading, and notebook paths

### Code quality

- Type hints on all function signatures — no untyped public APIs
- Docstrings on any function that isn't immediately obvious from its name and signature
- No mutable default arguments — `def f(x=None)` not `def f(x=[])`
- Catch specific exceptions — no bare `except:` or `except Exception:`
- No `print()` in production code — use `logger.debug/info/warning/error`
- No magic numbers — use named constants or config values
- No single-letter variable names outside comprehensions, lambdas, or loop counters
- Functions over 40 lines → consider splitting
- Nesting over 3 levels → consider early returns or extraction
- Every new function gets at least one test

### Configuration

- Never hardcode paths, secrets, config values, or hyperparameters
- Config files or env vars only
- Seed all randomness: `torch.manual_seed()`, `np.random.seed()`, `random.seed()`

### Resource-constrained execution

Ask before running if any of the following apply:

1. **Costly** — API calls, cloud resources, anything that incurs $ cost
2. **Token/memory intensive** — large file/model loads, datasets >10k rows
3. **Long-running** — model training, full test suites without `-k`, estimated >30s

Prefer:
- Dry-run flags (`--dry-run`, `-n`) before destructive or expensive ops
- Targeted `pytest -k <filter>` or specific file path over full suite
- Subsampled data for local validation — log the subsample size

---

## Workflow

Non-trivial tasks follow phases:

| Phase | Command | Artifact |
|-------|---------|----------|
| 1. Research | `/research <name>` | `.claude/docs/research/<name>.md` |
| 2. Plan | `/plan <name>` | `.claude/docs/plans/<name>.md` |
| 2.5. Plan Review | `/plan-review` | active plan (iterated) |
| 3. Execute | `/execute` | `.claude/docs/CHANGELOG.md` |
| 4. Review | `/review <name>` | `.claude/docs/reviews/<name>.md` + PR |

All phase artifacts live in `.claude/docs/` subdirectories (gitignored). `SESSION.md` tracks the active plan and research files under `## Active docs`. Only `CLAUDE.md` lives at the project root.

### Tooling

- `uv run pytest tests/unit/` — unit only (fast, no external deps)
- `.env` never committed; `.env.example` is the template

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
