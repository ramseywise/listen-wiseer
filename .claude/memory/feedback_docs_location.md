---
name: Phase artifact location convention
description: All PLAN/RESEARCH/CHANGELOG/EVAL/SESSION docs go in .claude/docs/, not project root. Only CLAUDE.md at root.
type: feedback
---

All phase artifacts must go in `{project}/.claude/docs/`, not the project root.

**Why:** Root-level PLAN.md, RESEARCH.md, CHANGES.md etc. add noise to the repo and are visible to anyone cloning. These are working docs "for us not the app." `.claude/` is already gitignored in all projects.

**How to apply:**
- `/research` → writes `.claude/docs/RESEARCH.md`
- `/plan` → writes `.claude/docs/PLAN.md`
- `/execute` → appends to `.claude/docs/CHANGELOG.md` per step (no CHANGES.md)
- `/review` → writes `.claude/docs/EVAL.md`
- `/start` → reads `.claude/docs/SESSION.md` + `CLAUDE.md`
- `/end` → updates `.claude/docs/SESSION.md`
- `CLAUDE.md` stays at project root (committed — guidance for Claude)
- `.claude/` is gitignored in all projects — nothing inside is committed
- Never create CHANGES.md or SESSION.md at root; CHANGELOG.md in `.claude/docs/` is the single execution record
