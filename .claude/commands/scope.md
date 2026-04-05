---
name: scope
description: "Quick sizing of a task. Estimate files touched, complexity, and whether it needs the full pipeline or just /debug."
tools: Read, Grep, Glob, Bash
---

The user describes a task in `$ARGUMENTS`. Quickly assess its scope without implementing anything.

## What to check

1. **Grep/Glob** for relevant files, functions, and imports
2. **Read** key files to understand current state
3. Count files that would need changes

## Output format

```
## Scope: [task summary]

**Files touched**: N files
- `src/path/file.py` — [what changes]
- ...

**Complexity**: low / medium / high
**Dependencies**: [any new packages, config, or API keys needed]
**Test impact**: [which test files need updates]

**Recommendation**: /debug | /plan | full pipeline
```

Keep it under 20 lines. This is a quick assessment, not a research phase.
