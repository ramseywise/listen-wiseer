---
name: scope-initiative
description: "Take a named initiative and produce a Linear-ready technical backlog: failure modes, HMWs, research section, task backlog with acceptance criteria and t-shirt sizes, dependency mapping, and Linear hierarchy. Use when an initiative is named and agreed on."
tools: Read, Bash, Grep, Glob, WebSearch, Write
---

Scope the following initiative into a Linear-ready backlog: $ARGUMENTS

# Initiative Scoping

Take a named initiative from a design sprint (or any other source) and produce a Linear-ready technical backlog.

## Inputs required before starting

Ask for these if not already provided:

1. **Initiative name and one-line goal** — what does this initiative deliver?
2. **Known failure modes** — 3-5 distinct ways the system currently fails in this area. Named as patterns, not symptoms (e.g. "corpus quality -> coverage without noise" not "bad retrieval")
3. **Brief or requirements doc** — paste or reference the relevant sections
4. **Existing assets** — prior prototypes, research docs, phase plans, analogous systems
5. **Team roles available** — FE / BE / AI Eng / Ops / Analytics
6. **MVP scope** — what is explicitly in vs out for the first delivery?

---

## Section 1 — Failure modes and HMWs

For each known failure mode:

| # | Failure mode | Pain point | HMW |
|---|---|---|---|

Rules:
- Failure mode name: `root cause -> observed symptom` (e.g. "context augmentation -> personalisation")
- Pain point: one sentence — what the user or agent experiences
- HMW: outcome-oriented, not solution-prescribing, phrased positively
- Every subsequent task must trace back to at least one failure mode

State the core problem in one paragraph: why this initiative is the enabling layer for the product objectives it serves.

---

## Section 2 — Research

### Existing internal assets
| Asset | Status | Relevance |

Include prior prototypes, production systems being replaced, datasets, codebases, benchmark baselines. For each, state whether it can be reused directly, adapted, or only used as reference.

### Libraries and tools under consideration
| Layer | Option | Notes |

Cover every technical layer: embedding model, retrieval, reranking, vector store, agent graph, evaluation, tracing, session storage, query rewriting. Note the key trade-off for each option.

Flag the tracing backend decision explicitly — it affects multiple tasks and is often decided by default.

### Technical unknowns and roadblocks

**Technical unknowns** — decisions that must be made before implementation begins. One bullet per unknown, stating what it blocks.

**Roadblocks and dependencies:**
| Dependency | Blocks | Owner | Status |

Flag the highest-risk dependency explicitly. For most AI initiatives this is data access.

---

## Section 3 — Task backlog

### Initiative goal
One paragraph: what does done look like? Include 3-5 measurable criteria for MVP definition of done.

### Task format

```
### Task N — [descriptive name]
*Failure mode: [which failure mode(s) this addresses]*

**Goal:** One sentence — what problem does this task solve?

**Deliverable:** What exists when this task is done? A running service, a validated model, an agreed schema document, a dataset. Not "implement X".

**Key work:**
- Bullet list of major implementation steps
- Each bullet is a concrete action, not a category
- Include library/tool choices where decided
- Flag cross-team interface points explicitly

**Risks and questions:**
- What could go wrong or block this task?
- What decisions are still open?
- What cross-team alignment is needed?

**Size: S / M / L / XL**
```

T-shirt sizes:
- **S** — one engineer, less than a week, few unknowns
- **M** — one engineer, one to two weeks, some unknowns or cross-team coordination
- **L** — one or two engineers, two to four weeks, significant unknowns or sequential dependencies
- **XL** — multiple engineers, more than a sprint, major architectural decisions or external blockers

### Task ordering rules
- Prerequisites first (schema decisions, model selection, data access)
- Day-one decisions that are expensive to change later must be in the critical path
- Post-MVP tasks are included but clearly labelled

---

## Section 4 — Summary table and critical path

### Summary table
| # | Task | Failure mode | Size | Key dependency | Owner | MVP? |

### Critical path
One paragraph naming:
- Week-1 decisions that block everything else
- Highest-risk external dependency
- Tasks that must be designed together even if delivered sequentially
- Threshold conditions for conditional post-MVP tasks

### Linear project grouping
| Linear project | Tasks | Failure modes |

Each Linear project should be a coherent workstream a single sub-team could own.

---

## Section 5 — Open questions

Numbered list of questions that must be answered before sprint planning. Each names who must answer it.

Categories: data access, infrastructure, product decisions, ownership, policy, phasing.

---

## Linear hierarchy

```
Initiative (Linear initiative)
  +-- Project 1 — [workstream name]  (Linear project)
        +-- Issue: Task N — [name]   (Linear issue)
        |     - Description: goal + deliverable
        |     - Acceptance criteria: measurable conditions
        |     - Estimate: t-shirt size
        |     - Blocking: [Task M] (if applicable)
        +-- Issue: Task M — [name]
  +-- Project 2 — [workstream name]
        +-- ...
```

### Acceptance criteria format
- Given [condition], when [action], then [measurable outcome]
- Include at least one metric-based criterion
- Include at least one integration criterion

### Blocking relationships
- **Hard block**: Task cannot start without the blocker being merged
- **Soft dependency**: informed by, but can start with conservative placeholders

---

## Gap-checking against research docs

When existing research docs are provided, cross-reference against the backlog:

1. List every solution and dependency named in the docs
2. Check each against backlog tasks — covered, partial, or missing?
3. Flag gaps: what is in the docs but not in the backlog?
4. Add missing items as tasks, citing the source doc

---

## Brief format (when no sprint exists)

If no design sprint has been run, produce a condensed brief:

1. **Why** — 2-3 core failure modes, one HMW per mode, north star connection
2. **Research** — existing assets, libraries/tools, technical unknowns, roadblocks
3. **What** — initiative goal, MVP definition of done, 6-9 tasks (same format as above)
4. **Summary table** + critical path
5. **Open questions**

Present each section and ask for confirmation before continuing.

---

## Quality checks

- Every task traces to at least one named failure mode
- Every deliverable is concrete (running system, document, dataset) — not "implement X"
- Every task has at least one risk or open question
- Week-1 decisions are named and sequenced first
- Post-MVP tasks are present and architecture is compatible with them
- Day-one decisions (embedding model, vector store, metadata schema) appear in the first sprint
- Highest-risk external dependency is named with owner and consequence if unresolved
- Linear grouping produces workstreams a single sub-team could own
- Acceptance criteria are measurable, not descriptive
