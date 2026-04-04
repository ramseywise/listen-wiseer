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

## Style Rules

### Python

- `uv` only (`uv add`, `uv run`, `uv sync`) — never pip or poetry
- Pydantic v2 for all models and settings
- ruff for lint/format — run before committing
- pyright for type checking when configured per project
- `from __future__ import annotations` in all modules
- Type annotations on all function signatures
- f-strings over `.format()` or `%`

### Data

- **Polars not pandas** — lazy frames for large data, eager for small
- **DuckDB** for local analytics and joins — avoid loading full tables into memory
- Parquet for cached intermediate data; never CSV for processed outputs
- Column names: `snake_case`

### API / IO

- `httpx` not `requests`; async-first for I/O
- Always close connections (context managers or explicit `.close()`)
- Pydantic models at API boundaries, not raw dicts

### Don'ts

- No hardcoded paths, secrets, or hyperparameters — config files / env vars only
- No pandas, no stdlib `logging`, no `print()` in `src/`
- No mutable default arguments
- No bare `except` clauses
- No notebooks committed with output cells

---

## Logging Standard — structlog everywhere

Always use `utils.logging` (structlog). Never use stdlib `logging` or `print()` in `src/`.

### Module pattern

```python
from utils.logging import get_logger

log = get_logger(__name__)  # one per file, module-level
```

### Entry point setup

```python
from utils.logging import configure_logging

configure_logging()                    # dev: colored console
configure_logging(render_json=True)    # prod/CI: JSON lines
```

### Event naming

Dot-separated `module.action` — never free-form strings:

```python
log.info("sync.playlists", n=len(playlists))
log.info("train.gmm.fit", n_components=8, silhouette=sil)
log.error("etl.fetch.failed", error=str(exc), playlist_id=pid)
```

### Rules

- Bind counts and identifiers as structured fields — not f-string interpolation
- `debug` for per-item loops; `info` for phase transitions; `error` for caught exceptions
- Use `structlog.contextvars.bind_contextvars(run_id=...)` for request/session scope

---

## ML / DS Best Practices

### Reproducibility

- Always seed: `np.random.seed(42)`, `random_state=42` in sklearn, `seed=` in Polars `.sample()`
- Pin hyperparameters in config, never inline in code
- Log model params and metrics at train time (structlog)
- Save artifacts with joblib to `models/` — never commit `.pkl` files

### Pipelines

- Wrap all preprocessing + model in sklearn `Pipeline` — prevents data leakage
- Fit scaler on train split only, transform test with fitted scaler
- `CalibratedClassifierCV` for calibrated probability outputs

### Evaluation

- Always report: accuracy, precision, recall, f1, roc_auc, precision@K
- Silhouette score for clustering quality
- Compare against a naive baseline (e.g. majority class, random)
- Log eval results as structured fields, not print statements

### Data

- Notebooks are for exploration only — move validated logic to `src/`
- Subsample for local dev; log the subsample size and seed
- Validate corpus size before training — log `n_rows`, `n_features`
- `null_values=["", "NA", "NaN"]` on all CSV reads

### Don'ts

- No pandas in ML code — Polars in, numpy arrays to sklearn
- No global mutable state in model modules
- Never load real data files or model weights in unit tests — synthetic fixtures only
- No training inside notebooks — notebooks call `python -m module.train`

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
| 1. Research | `/research` | `.claude/docs/RESEARCH.md` |
| 2. Plan | `/plan` | `.claude/docs/PLAN.md` |
| 2.5. Plan Review | `/plan-review` | `.claude/docs/PLAN.md` (iterated) |
| 3. Execute | `/execute` | `.claude/docs/CHANGELOG.md` |
| 4. Review | `/review` | `.claude/docs/EVAL.md` + PR |

All phase artifacts live in `.claude/docs/` (gitignored). Only `CLAUDE.md` lives at the project root.

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
