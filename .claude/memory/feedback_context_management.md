---
name: Context management — SESSION.md pattern adopted
description: User adopted SESSION.md pattern for token tracking, session handoff, and gotcha rolling context
type: feedback
---

User wants active context budget management. Adopted the following system:

**SESSION.md** at project root (committed):
- Current step + test count
- Token log (start/end from status bar, turn count, compacted?)
- Active gotchas (non-obvious bugs/decisions)
- Open questions/blockers
- Next session prompt (copy-paste starter)

**Why:** Conversation accumulation is the main token killer (not output code). CLAUDE.md carries too much history. SESSION.md offloads the rolling state so CLAUDE.md stays lean.

**How to apply:**
- Read SESSION.md first at session start, before any coding
- Update it at session end before `/clear`
- Keep project CLAUDE.md to: stack, commands, current step only, gotchas — NO completed step history
- Completed steps go to CHANGES.md only
- `/compact` message: `keep current step N, test count, open gotchas, and next 2 actions`
- At session end: update CLAUDE.md with accurate current state (what's built, what's next, key decisions); replace aspirational content with status tables; add "Key implementation decisions" section with gotchas; remove stale sections
- **Compact before each plan step**: update plan + memory first, then `/compact`, then execute. User wants this as a hard discipline — don't skip it.
