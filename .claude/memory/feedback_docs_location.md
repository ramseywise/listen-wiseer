---
name: Phase artifact location convention
description: Pipeline docs use named subdirectories under .claude/docs/ (plans/, research/, reviews/). SESSION.md tracks active docs. Only CLAUDE.md at project root.
type: feedback
---

All phase artifacts go in named subdirectories under `.claude/docs/`:

| Phase | Path pattern |
|-------|-------------|
| Research | `.claude/docs/research/<name>.md` |
| Plan | `.claude/docs/plans/<name>.md` |
| Review/Eval | `.claude/docs/reviews/<name>.md` |
| Changelog | `.claude/docs/CHANGELOG.md` (singleton, append-only) |
| Session | `.claude/docs/SESSION.md` (singleton) |

**Why:** Flat files (`PLAN.md`, `RESEARCH.md`) don't scale — multiple phases produce multiple plans. Named files in subdirectories create a natural archive (e.g. `phase3a_preprocessing.md` through `phase6_dashboard.md`).

**How to apply:**
- `/research <name>` → writes `.claude/docs/research/<name>.md`, updates SESSION.md active docs
- `/plan <name>` → writes `.claude/docs/plans/<name>.md`, updates SESSION.md active docs
- `/execute` → reads active plan from SESSION.md `## Active docs` section
- `/review <name>` → writes `.claude/docs/reviews/<name>.md`
- `/plan-review` → reads active plan + research from SESSION.md
- `SESSION.md` has `## Active docs` section pointing to current plan and research files
- `CLAUDE.md` stays at project root (committed)
- `.claude/` is gitignored — nothing inside is committed
- Never create flat `PLAN.md`, `RESEARCH.md`, or `EVAL.md` in `.claude/docs/`
