# Phase 4 — Long-Term Memory for ENOA

> Sources: "Long-Term Agentic Memory with LangGraph" (Langmem/Coursera) and
> "LLMs as Operating Systems: Agent Memory" (Letta/MemGPT, Coursera).
> These steps add persistent memory across sessions to the ENOA recommendation agent.
> All steps are independent; execute in order 4.1 → 4.5 for progressive capability.

---

## Step 4.1 — Cross-session recall: Redis checkpointer

**Gap**: Phase 3 uses `MemorySaver` — in-process only, lost on restart. Phase 4 requires
cross-session persistence.

**What**: Replace `MemorySaver` with `AsyncRedisSaver` (same pattern as help-assistant).

**Files**:
- `src/agent/graph.py` — swap `MemorySaver()` for `AsyncRedisSaver` with `default_ttl=1440`
  (24h in minutes)
- `src/agent/dependencies.py` (new) — lifespan management: `await saver.setup()` on startup,
  `await saver.__aexit__(None, None, None)` on shutdown
- `.env.example` — add `REDIS_URL=redis://localhost:6379`

**Note**: Use direct constructor + `setup()`, not `from_conn_string` context manager —
same gotcha as help-assistant.

**Multi-turn input**: Pass `{"messages": [HumanMessage(content=query)]}` not `initial_state()`.
LangGraph's `add_messages` reducer handles the merge. This is the single highest-impact fix.

---

## Step 4.2 — Episodic memory: past sessions as few-shots

**What**: Store past recommendation sessions (user request + track list returned) and inject the
2 most similar past sessions as few-shot examples into the ENOA generation prompt.

**Files**:
- `src/agent/memory_store.py` (new) — `InMemoryStore` (dev) or Postgres store (prod):
  ```python
  from langgraph.store.memory import InMemoryStore
  store = InMemoryStore(index={"embed": "openai:text-embedding-3-small"})
  ```
- `src/agent/graph.py` — compile graph with `store=store`; in the synthesize node, call
  `store.search(("enoa", user_id, "sessions"), query=user_request, limit=2)` and prepend
  results to the prompt as examples
- `src/agent/nodes.py` — after successful recommendation, `store.put(namespace, key, session_dict)`
  where `session_dict = {"request": query, "tracks": track_list, "ts": isoformat}`

**Namespace**: `("enoa", user_id, "sessions")` — scoped per user via `config["configurable"]["langgraph_user_id"]`

**Test**: `tests/unit/agent/test_memory_store.py` — `test_episodic_roundtrip`: put a session,
search with similar query, assert it's retrieved.

---

## Step 4.3 — Semantic memory: ENOA user taste profile

**What**: Let the agent write and update facts about the user's taste across sessions
(e.g. "prefers zouk over kizomba", "dislikes electronic BPM > 140").

**Files**:
- `src/agent/nodes.py` — add `manage_memory_tool` and `search_memory_tool` to the agent's
  tool list:
  ```python
  from langmem import create_manage_memory_tool, create_search_memory_tool
  namespace = ("enoa", "{langgraph_user_id}", "taste")
  manage_memory_tool = create_manage_memory_tool(namespace=namespace)
  search_memory_tool = create_search_memory_tool(namespace=namespace)
  ```
- Same `store` instance from Step 4.2

**Hot path**: semantic tools run while responding — adds ~200ms per turn with a tool call.
Acceptable for ENOA since recommendations are already slow (corpus scan + LLM).

**Test**: `tests/unit/agent/test_memory_store.py` — `test_taste_profile_update`: invoke agent
twice; second turn's prompt should include fact from first turn.

---

## Step 4.4 — Procedural memory: per-user recommendation strategy

**What**: Store per-user system prompt instructions that evolve over time
(e.g. "always explain why this track fits the user's ENOA zone").

**Files**:
- `src/agent/memory_store.py` — add `get_procedural_prompt(user_id)` and
  `update_procedural_prompt(user_id, new_instructions)` helpers using `store.get`/`store.put`
  under namespace `("enoa", user_id, "strategy")`
- `src/agent/nodes.py` — prepend procedural instructions to system prompt at graph start;
  fall back to default ENOA system prompt if namespace is empty
- Background optimizer (Phase 4.5) will call `create_multi_prompt_optimizer` to update this

**Test**: `tests/unit/agent/test_memory_store.py` — `test_procedural_fallback`: empty store
returns default prompt; populated store returns stored instructions.

---

## Step 4.5 — Background prompt optimizer

**What**: A separate background agent (not in the hot path) reviews conversation trajectories
and feedback signals, then updates the procedural memory for each user.

**Files**:
- `src/agent/optimizer.py` (new):
  ```python
  from langmem import create_multi_prompt_optimizer
  optimizer = create_multi_prompt_optimizer(
      model="anthropic:claude-sonnet-4-6",
      kind="metaprompt",
  )
  ```
- Call `optimizer.invoke({"trajectories": [...], "prompts": [current_prompt]})` after a session
  ends or on a schedule; write result back to procedural memory store
- `src/agent/graph.py` — add a `END` edge that triggers optimizer asynchronously (fire-and-forget
  via `asyncio.create_task`) so it doesn't block the user response

**Note per Langmem team**: Claude Sonnet outperforms GPT for prompt optimization. Use
`claude-sonnet-4-6`.

**Test**: `tests/unit/agent/test_optimizer.py` — mock optimizer; assert it's called with the
correct trajectory shape after graph END.

---

## Step 4.6 — History overflow: trim or summarize

**Gap** (from MemGPT course): no strategy for long sessions. Zouk/kizomba exploration sessions
can easily hit 20+ messages.

**What**: Add a `_trim_history` node before synthesize. If message count > 20, apply
`trim_messages(strategy="last")`. When trim causes visible context loss in testing, upgrade to
a summarization node (one extra LLM call — Haiku, cheap).

**Files**:
- `src/agent/graph.py` — add trim node + conditional edge (same pattern as help-assistant H1)
- `src/agent/nodes.py` — `def trim_history(state): return {"messages": trim_messages(...)}`

**Tradeoff**: trim is cheap but loses earlier context; summarization preserves it at ~$0.0001/session.
Start with trim.

---

## Step 4.7 — Memory statistics in ENOA prompt

**What**: Tell the agent how much it knows before it responds — "You have 3 past sessions on
record. 2 taste facts stored." Mirrors MemGPT's memory statistics in context.

**Files**:
- `src/agent/nodes.py` — at graph start, query store for `list_namespaces()` counts;
  inject as a `<memory_stats>` block in the system prompt

**Test**: `tests/unit/agent/test_nodes.py` — `test_memory_stats_injected`: populated store
produces non-empty stats block in prompt.

---

## Out of Scope (Phase 4)

- **Letta framework** — MemGPT course uses Letta server + client SDK. We build on LangGraph +
  Langmem directly — same concepts, no Letta dependency needed.
- **Shared memory blocks across agents** — only one agent in Phase 4. If a separate eval or
  curator agent is added later, shared blocks become relevant.
- **HITL interrupt_before** — could be useful for ENOA ("confirm before adding to taste
  profile?"). Defer — adds friction in the v1 conversational flow.
- **Vector DB for memory store** (Postgres/pgvector) — `InMemoryStore` for dev; swap at deploy
  time. Episodic/semantic search degrades gracefully to keyword search without embeddings.

---
