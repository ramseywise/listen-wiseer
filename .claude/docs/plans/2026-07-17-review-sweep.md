# Review — sweep 2026-07-17

Status: EXECUTED
Scope: uncommitted changes (5 files, all machine-consumed docs/config — today's tooling
migration: phase-status flips, settings wildcard fix, pipeline repathing, Refs line).
Mode: fast (tests skipped). No IN PROGRESS plan covers this diff → standalone report.

## Mechanical

- Lint: PASS (`make lint` — ruff check + format, 52 files)
- Tests: SKIPPED (fast)

## Findings (ranked)

- **[Non-blocking]** `.claude/skills/pipeline/SKILL.md:20,22` — stale command names
  survive today's repathing: `/plan-review` → `/plan review`, `/debug` → `/code-debug`,
  `/code_review` → `/code-review`, `/refactor` → `/plan-refactor`. Users invoking the
  documented names get no dispatch.
- **[Non-blocking]** `.claude/settings.json:45` — hook matcher `TodoWrite`: legacy tool
  name, hook silently never fires (same settings-rot class as the 2026-07-16 global fix).
  Update matcher (TaskCreate) or remove the hook.
- **[Non-blocking]** `CLAUDE.md` phase table — Phase 8 row says IN PROGRESS but
  `phase8-rag-rightsize-agentic-search.md:3` says `Status: EXECUTED (2026-07-07)`.
- **[Nit]** `.claude/settings.json:39` — hook glob still matches retired
  `SESSION.md|research/|reviews/` paths; harmless, cleanable.
- **[Nit]** `phase7c-memory-genre-polish.md:116` — references `memory/project_listen_wiseer.md`
  which never existed; historical (plan EXECUTED), no action.

## Contract (SANYI)

No contract (no SANYI.md at repo root) — skipped.

## Docs

- Proposed diffs (machine-consumed, apply on approval):
  1. `pipeline/SKILL.md:20` `/plan-review` → `/plan review`; `:22` ad-hoc list →
     `/code-debug`, `/code-review`, `/plan-refactor`
  2. `CLAUDE.md` phase table: Phase 8 `IN PROGRESS` → `✓ DONE`
  3. `settings.json:45` matcher `TodoWrite` → `TaskCreate` (or delete hook block)
- Flags (human-consumed): none — README not touched by this diff.

## Verdict

[x] Approved with minor fixes — diff itself is correct and consistent; findings are
pre-existing staleness the diff exposed, all in machine-consumed files.

## Resolution — 2026-07-17 (Ramsey-approved)

All 3 non-blocking findings fixed same session: pipeline command names, Phase 8 row,
`TodoWrite` → `TaskCreate|TaskUpdate` matcher (hook now logs tool input; old
`.newTodos` response field was dead). Nits left as-is (harmless glob, historical plan
reference). settings.json jq-validated.
