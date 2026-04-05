Audit and clean stale `.claude/` state. Work through these steps in order:

## 1. Global memory (`~/.claude/projects/-Users-wiseer-workspace/memory/`)

Read every `.md` file (skip MEMORY.md itself). For each, judge:
- **Stale project state** (phase status, audit results, open TODOs that may be resolved) — present a summary and ask which to drop or update
- **Redundant feedback** — two memories saying the same thing → merge into the more complete one
- **Outdated decisions** — anything that contradicts current CLAUDE.md or known project state → flag for removal

After review, apply approved deletions/merges, then rewrite MEMORY.md index to reflect the final set.

## 2. Project `.claude/docs/` in the current project directory

Check for:
- `.claude/docs/plans/` — plans for completed/merged tasks are archival. Flag any that are stale but not marked done.
- `.claude/docs/research/` — research files for completed tasks can be deleted. List candidates and ask.
- `.claude/docs/reviews/` — review files for merged PRs can be deleted. List candidates and ask.
- `CHANGELOG.md` — if all entries are merged, prompt to archive or clear the `[Unreleased]` section
- `SESSION.md` — if "current position" is stale (old date, completed step), prompt to reset or archive the next-session prompt. Check `## Active docs` for stale pointers.

Do NOT touch `CLAUDE.md` or `SESSION.md` content beyond what the user confirms.

## 3. Report

Output a short table: what was deleted, what was merged, what was kept and why. No trailing summary beyond the table.
