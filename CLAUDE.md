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
