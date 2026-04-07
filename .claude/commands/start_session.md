Read `.claude/docs/SESSION.md` and `CLAUDE.md` in the current project directory.

If `.claude/docs/SESSION.md` does not exist, create it from this template and tell the user to fill in the project details:

```markdown
# SESSION.md — <project name>

## Active docs

- **Plan**: (none yet)
- **Research**: (none yet)

## Current position

- **Last updated**: <today>

## Active gotchas

(none yet)

## Open questions

(none yet)

## Next session prompt

Cold start: no active task. Run /research or /plan to begin.
```

Then output:
1. **Current position** — step, test count, last updated
2. **Active gotchas** — list them concisely
3. **Next action** — one sentence: what we're doing first
4. **Token tip** — remind me to /compact at 40% and check the status bar

Do NOT read `.claude/docs/PLAN.md`, `.claude/docs/RESEARCH.md`, or any other doc unless SESSION.md says something is blocked or unclear. Keep the output short — this is a session kickoff, not a briefing.
