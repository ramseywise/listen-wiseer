Audit and clean stale `.claude/` state. Work through these steps in order:

## 1. Global memory (`~/.claude/projects/-repo/memory/`)

Read every `.md` file (skip MEMORY.md itself). For each, judge:
- **Stale project state** (`project_decision`, `project_milestone`, `project_problem` subtypes) — phase status or open problems that may be resolved → flag for removal or update
- **Redundant feedback** — two `feedback_preference` or `feedback_pattern` files saying the same thing → merge into the more complete one
- **Outdated decisions** — anything that contradicts current CLAUDE.md or known project state → flag for removal
- **Mistyped files** — any file not using the `<type>_<subtype>_<topic>.md` naming convention → suggest rename

After review, apply approved deletions/merges/renames, then rewrite MEMORY.md index to reflect the final set.

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
