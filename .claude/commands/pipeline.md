---
description: "Map the full phased workflow; start from a chosen phase with human gates between artifacts."
---

# Workflow — full pipeline

## Phases (in order)

| Phase | Command | Artifact | Gate |
|-------|---------|----------|------|
| 1. Research | `/research` | `RESEARCH.md` | Human reviews before continuing |
| 2. Plan | `/plan` | `PLAN.md` | Human reviews before continuing |
| 2.5. Plan Review | `/plan-review` | `PLAN.md` (iterated) | Blockers resolved, questions answered |
| — | `/compact` | — | **Run before execute** |
| 3. Execute | `/execute` | `CHANGES.md` | Human confirms each step |
| 4. Review | `/review` | `EVAL.md` + PR | Verdict: go / no-go |

**Plan updates anytime:** `/plan-review` re-runs the review and patches PLAN.md.

Ad-hoc (skip pipeline): `/debug`, `/code_review`, `/refactor`.

## On invoke

1. If the user asked to **run the full workflow**: run only the first applicable phase. Do not auto-chain — gates matter.
2. If the user named a **specific phase** (e.g. "just plan"): run that phase only.
3. If unclear: show the table above and ask.

## All commands run in current context

Do not spawn subagents or use the Agent/Skill tools for any pipeline phase. Run research, plan, plan-review, and execute directly in the main conversation using Read, Write, Grep, Glob, Bash, and WebSearch tools.
