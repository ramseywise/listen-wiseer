# Phase 5 — Eval Framework (Arize / Evaluating AI Agents gaps)

> **Prerequisite**: Phase 4 complete. Execute once the agent is live and handling real queries.

## Goal

Structured evals at each agent layer: MCP tool selection (router), recommendation quality
(skill), and trajectory (loop detection). Eval-driven iteration from real user data.

---

## Step 5.1 — MCP tool selection eval dataset

**Gap**: ENOA's agent selects between 4 `recommend_*` MCP tools + Spotify tools. No formal eval
on whether it picks the right tool for a given user request.

**What**:
- Build `evals/datasets/tool_selection_eval.jsonl` — 30+ labeled examples:
  `{user_request, expected_tool, expected_params}` (e.g. "find tracks like X" → `recommend_tracks`)
- Code-based exact match on `expected_tool`
- Run with: `PYTHONPATH=src uv run python -m evals.tasks.tool_selection_eval`

**Files**:
- `evals/datasets/tool_selection_eval.jsonl` (new)
- `evals/tasks/tool_selection_eval.py` (new — runs agent, extracts tool calls from trace)

**Pass threshold**: tool selection accuracy ≥ 85% on labeled dataset.

---

## Step 5.2 — Trajectory eval (loop detection + step presence)

**Gap**: ReAct loop can get stuck calling the same tool repeatedly. No loop detection in place.

**What**:
- Offline trajectory eval on collected traces
- Loop detection: flag any trace where same tool called consecutively > 2 times
- Required-step presence: assert `recommend_*` appears in every non-chit-chat trace

```python
def detect_loops(tool_calls: list[str], threshold: int = 2) -> bool:
    for i in range(len(tool_calls) - threshold):
        if len(set(tool_calls[i:i+threshold+1])) == 1:
            return True
    return False
```

- Use `max_iterations` guard in LangGraph graph as hard stop (already standard in ReAct agents)

**Files**:
- `evals/tasks/trajectory_eval.py` (new)

---

## Step 5.3 — Recommendation quality LLM-as-judge

**Gap**: No eval on the quality of the final recommendation response — does it address the user's
actual request? Is it specific enough? Does it hallucinate track info?

**What**:
- Claude Sonnet judges Haiku recommendation responses (PASS/FAIL)
- Judge criteria: `tool_appropriate`, `response_addresses_request`, `no_hallucinated_facts`
- Build 30+ sample eval set from real conversations
- Validate judge against manual labels before using in CI

**Files**:
- `evals/graders/recommendation_judge.py` (new)
- `evals/datasets/recommendation_eval.jsonl` (new)

---

## Step 5.4 — Production monitoring (custom LangFuse scores)

**What**: Add custom score logging per request for monitoring regressions in production.

- `tool_selected` — track distribution of which recommend_* tools are called
- `loop_detected` — flag traces where loop detection fires
- `memory_hits` — did episodic/semantic memory contribute to the response?

**Alert thresholds**:
- Loop rate > 5% of traffic → investigate agent reasoning
- Tool accuracy regression (compare weekly rolling avg vs baseline)

**Files**:
- `src/agent/nodes.py` — add LangFuse custom score logging at graph END node

---

## Out of Scope (Phase 5)

- **Full Phoenix/Arize integration** — LangFuse is already planned; Phoenix adds cost without
  clear advantage at current scale. Revisit if multi-agent pattern is added.
- **Eval dataset before building** — Phase 3 is already being built; I1 style TDD applies to
  new tools, not retrofitted to existing ones.

---
