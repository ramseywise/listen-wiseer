Status: COMPLETE
Completed: 2026-07-30
Evidence: merged via PR #83 (LIS-77-runtime-bugs); 475 unit tests pass, lint clean, static check confirms _store passed (not bare get_store()), TestSynthesize::test_synthesize_invokes_shared_llm passes (import path exercised).

# LIS-77 — Fix unawaited async get_store() and broken _llm import

GitHub issue: #77
Source: `/akira all` sweep 2026-07-27

## Research

Two runtime bugs, one latent type-hint bug, all confirmed by direct read:

**Bug 1 — `src/app/main.py:116`**
```python
schedule_optimization(user_id, result["messages"], get_store())
```
`get_store()` (`src/agent/memory_store.py:59`, `async def get_store() -> BaseStore`) is
called without `await` — passes an unawaited coroutine object where `schedule_optimization`
(`src/agent/optimizer.py:97`) expects a `BaseStore`. `schedule_optimization` itself is
sync (fire-and-forget via `loop.create_task`), so `await` can't just be added at the call
site — the fix must reuse the `store` object already created in `_get_graph()`
(`main.py:34`) via module-level caching, mirroring the existing `_graph` singleton
pattern.

**Bug 2 — `src/agent/tools/web_search.py:93`**
```python
from agent.graph_nodes import _llm  # shared Haiku instance
```
`agent.graph_nodes` defines `_llm_instance: ChatAnthropic | None` (module global,
`graph_nodes.py:65`) and `_get_llm() -> ChatAnthropic` (`graph_nodes.py:69`, lazy
singleton accessor) — there is no `_llm` name. This import raises `ImportError` the
first time `_synthesize()` (`web_search.py:91`) executes, which only happens when
`_agentic_search` fans out to >1 sub-query. `tests/unit/agent/test_web_search.py`
patches `agent.tools.web_search._synthesize` directly in the multi-hit test
(`test_complex_query_fans_out_and_synthesizes`, line 126-128), so the function body —
and its broken import — never actually runs under test.

**Bug 3 (type hint) — `src/agent/optimizer.py:43,100`**
`optimize_prompt(user_id, messages, store: InMemoryStore)` and
`schedule_optimization(user_id, messages, store: InMemoryStore)` both annotate `store`
as `InMemoryStore`, but the only real producer is `get_store() -> BaseStore`, which
returns `AsyncPostgresStore` in prod (`memory_store.py`) per the dev/prod split noted in
repo CLAUDE.md ("`InMemoryStore` used for cross-session memory in dev; Redis/Postgres for
prod"). Narrow annotation is actively wrong for the prod path; fix to `BaseStore`.

## Plan

### Step 1 — Fix `main.py`: cache the store, await it once, pass the object

**File**: `src/app/main.py`

Reuse the module-level singleton pattern already used for `_graph` (lines 27-37). Add a
`_store` global, populate it inside `_get_graph()` (already the single place `get_store()`
is awaited), and pass that cached object to `schedule_optimization` at line 116 instead
of calling `get_store()` again unawaited.

```python
_graph = None
_store: BaseStore | None = None


async def _get_graph():
    global _graph, _store  # noqa: PLW0603
    if _graph is None:
        checkpointer = await get_checkpointer()
        _store = await get_store()
        _graph = build_graph(checkpointer=checkpointer, store=_store)
        log.info("app.graph_built")
    return _graph
```

At line 116:
```python
schedule_optimization(user_id, result["messages"], _store)
```

Add import: `from langgraph.store.base import BaseStore` (for the type annotation).

`_store` is guaranteed non-`None` by the time line 116 runs, because `on_message` always
calls `await _get_graph()` first (line 83), which populates `_store` on first call and
is a no-op cache-hit thereafter.

**Acceptance criteria**:
- `_store` global added, typed `BaseStore | None`, set inside `_get_graph()` before
  `build_graph()` is called.
- Line 116 passes `_store`, not `get_store()`.
- No remaining unawaited call to `get_store()` in the file (`grep -n "get_store()" src/app/main.py` shows only the `await get_store()` inside `_get_graph`).
- `ruff` / `pyright` clean (hook-enforced on write).

### Step 2 — Fix `web_search.py`: import the real accessor

**File**: `src/agent/tools/web_search.py:93`

```python
from agent.graph_nodes import _get_llm  # shared Haiku instance
```

Line 100 changes from `_llm.invoke(...)` to `_get_llm().invoke(...)`:
```python
response = _get_llm().invoke([HumanMessage(content=prompt)])
```

**Acceptance criteria**:
- Import resolves (`python -c "from agent.tools.web_search import _synthesize"` — see
  Step 4 verification, no `ImportError`).
- `_synthesize` calls `_get_llm()` and invokes on the returned instance, not on a raw
  import.

### Step 3 — Fix `optimizer.py` type hints

**File**: `src/agent/optimizer.py`

Line 15: `from langgraph.store.memory import InMemoryStore` → `from langgraph.store.base import BaseStore`.
Line 43: `store: InMemoryStore` → `store: BaseStore` (in `optimize_prompt`).
Line 100: `store: InMemoryStore` → `store: BaseStore` (in `schedule_optimization`).

Check whether `InMemoryStore` is still needed elsewhere in the file after this change
(it is not — both uses are the two annotations above) and drop the now-unused import
rather than leaving it dangling.

**Acceptance criteria**:
- No `InMemoryStore` import remains in `optimizer.py` unless still referenced.
- Both `store` parameters typed `BaseStore`.
- Existing tests (`tests/unit/agent/test_optimizer.py`) still pass unmodified — they
  construct `InMemoryStore()` instances and pass them positionally, which remains valid
  since `InMemoryStore` is a `BaseStore` subclass (structural compatibility only, no
  behavior change).

### Step 4 — Add regression coverage that would have caught both bugs

**File**: `tests/unit/agent/test_web_search.py`

Add a test that exercises `_synthesize` for real (no patching it away), only mocking
`_get_llm`'s return value, so the import path is actually executed:

```python
class TestSynthesize:
    def test_synthesize_invokes_shared_llm(self) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Synthesized [1]")
        with patch("agent.graph_nodes._get_llm", return_value=mock_llm):
            from agent.tools.web_search import _synthesize

            result = _synthesize(
                "bossa nova",
                [{"text": "hit one"}, {"text": "hit two"}],
            )
        assert result == "Synthesized [1]"
        mock_llm.invoke.assert_called_once()
```

Patch target is `agent.graph_nodes._get_llm` (where it's defined) since `_synthesize`
does a local `from agent.graph_nodes import _get_llm` inside the function body —
patching the source module works; patching `agent.tools.web_search._get_llm` would not
(name isn't imported at module scope).

No new test needed for `main.py` — Chainlit's `@cl.on_message` handler isn't under unit
test today (no `tests/unit/app/` directory exists) and adding Chainlit-session test
scaffolding is out of scope for a bug-fix issue. The `await`/cache fix is verified via
Step 5 static check instead (`AttributeError` was never actually raised as a test
failure — it was only reachable by running the app).

**Acceptance criteria**:
- New test fails against the pre-fix `web_search.py` (import error) and passes post-fix.
- `uv run pytest tests/unit/agent/test_web_search.py -v` — full file passes.
- `uv run pytest tests/unit/agent/test_optimizer.py -v` — unmodified, still passes.

### Step 5 — Static verification pass (no test harness covers `main.py`)

Since there's no unit test for the Chainlit entry point, verify Bug 1's fix by direct
import/type check rather than a new test file:

```bash
uv run python -c "
import ast, sys
tree = ast.parse(open('src/app/main.py').read())
src = open('src/app/main.py').read()
assert 'schedule_optimization(user_id, result[\"messages\"], get_store())' not in src, 'unawaited get_store() call still present'
assert 'schedule_optimization(user_id, result[\"messages\"], _store)' in src, 'fix not applied as expected'
print('OK')
"
uv run pyright src/app/main.py src/agent/optimizer.py src/agent/tools/web_search.py
```

**Acceptance criteria**:
- pyright reports no new errors on the three touched files (pre-existing unrelated
  errors, if any, are out of scope — compare against a pre-change baseline run).
- Manual grep confirms no bare `get_store()` call remains outside the single `await`
  site.

### Step 6 — Full suite + lint

```bash
uv run pytest tests/unit/ -v
make lint
```

**Acceptance criteria**:
- All unit tests pass, including the new `test_synthesize_invokes_shared_llm`.
- `make lint` clean.
- No regressions in `tests/unit/agent/test_web_search.py`, `test_optimizer.py`, or any
  test importing `agent.graph_nodes` / `agent.tools.web_search` / `agent.optimizer` /
  `app.main`.

## Branch / commit

Branch: `LIS-77-fix-unawaited-store-llm-import`, commits `fix: {desc} (#77)`.
Decision (2026-07-28): use global `LIS-{num}` convention for all repos. Repo-local
`feature/lin-{id}` convention in `listen-wiseer/CLAUDE.md:169` is superseded — update
that CLAUDE.md line during execution to match the global convention.

Current branch is `LIS-bug-dependabot-config` (unrelated) — this work needs its own
branch off `main` before Step 1 starts.

## Open questions

- None blocking. All three fixes are mechanical and scoped exactly to what issue #77
  describes; no design decisions required.
