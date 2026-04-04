---
name: code_pr
description: "Write a PR title and description from the current diff and CHANGES.md. Used by the review agent post-approval and standalone via /code_pr."
---

Write a pull request title and description for the current branch. Read the context, then produce the output — do not ask clarifying questions unless the diff is genuinely ambiguous.

## Read before writing

```bash
git diff main...HEAD --stat        # scope: which files changed
git log main...HEAD --oneline      # commit history on this branch
cat CHANGES.md 2>/dev/null         # deviations and what was implemented
cat PLAN.md 2>/dev/null            # original intent and goal
```

Read every changed file that isn't obvious from its name. The PR description must reflect what was actually shipped, not just what was planned.

## Title

- Under 60 characters
- Imperative mood: "Add X", "Fix Y", "Refactor Z" — not "Added" or "Adding"
- Specific: "Add playlist similarity scoring via GMM" not "Add new feature"
- No ticket numbers unless the project convention requires them

## Description

```markdown
## What
One paragraph. What does this change do from the user/caller's perspective? Avoid implementation details here.

## Why
One paragraph. What problem does this solve, or what capability does it add? Reference the goal from PLAN.md if it adds context.

## How
Bullet list of key implementation decisions — non-obvious choices only. If the approach is obvious from the diff, omit this section.
- [decision and why — e.g. "used CalibratedClassifierCV over raw probabilities because the model's raw outputs are poorly calibrated"]

## Testing
- Tests added/modified: [list as `tests/test_file.py::test_name`]
- Run with: `uv run pytest [targeted path] -v`
- Manual validation: [what was run and what was checked — "none" if fully covered by tests]

## Checklist
- [ ] Tests pass (`uv run pytest`)
- [ ] Lint passes (`uv run ruff check .`)
- [ ] No hardcoded paths or secrets
- [ ] CHANGES.md deviations documented (or "none")
```

## Rules

- Omit sections that have nothing to say — a PR with no non-obvious implementation decisions should have no `## How` section
- Do not pad — if the change is small, the description should be short
- If CHANGES.md records deviations from PLAN.md, the `## What` or `## How` must explain them
- The checklist is always included — it is the merge gate reminder, not optional prose
