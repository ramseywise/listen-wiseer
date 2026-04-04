# Plan: Phase 3 — LangGraph Agent + Chainlit UI
Date: 2026-04-03
Based on: RESEARCH.md
Phase 4 (RAG — Wikipedia + Tavily + ChromaDB) is a separate plan, steps below marked [Phase 4].

---

## Out of Scope

Declared before steps — these are plausible inclusions that are explicitly excluded:

- **`make train` / Step 11 smoke test** — Phase 2 blocker, not this plan. Must be resolved separately before Step 5 here.
- **Spotify `/recommendations` endpoint** — valuable but Phase 4+. Step 5 adds related-artists; the recommendations endpoint adds more complexity (seed marshalling, feature targets) and is deferred.
- **Last.fm API integration** — RESEARCH.md flags it as a fallback for niche artists. Deferred: adds a third external auth dependency. Wikipedia + web search covers the use case for now.
- **Multi-session memory persistence** — `MemorySaver` is in-process. Persisting across server restarts (Postgres checkpointer, etc.) is out of scope.
- **FAISS approximate nearest-neighbour** — 200ms corpus scan is acceptable for interactive use. ANN is an optimisation, not a correctness requirement.
- **Assigning ENOA coordinates to new tracks** — corpus tracks only. New-track handling is a data pipeline concern, not an agent concern.
- **Docker / infra changes** — `infrastructure/` is untouched.
- **Spotify write operations** — `save_tracks`, `add_to_playlist`, etc. The agent recommends; it does not write.
- **Streaming token output in Chainlit** — `LangchainCallbackHandler` enables it but per-token streaming from Haiku adds complexity. Step 9 uses `ainvoke`; streaming is a follow-up.

---

## Open Questions (resolved before planning)

- **Q: Web search service — Tavily or Brave?**
  A: Tavily. Has a native `TavilySearchResults` LangChain tool, no wiring needed. Free tier (1000 calls/mo) is sufficient for personal use. Requires `TAVILY_API_KEY` env var.
- **Q: Does `langchain-mcp-adapters` need installing?**
  A: No. Tools wrap Python functions directly as `StructuredTool`. Confirmed working.
- **Q: How should ENOA-missing tracks be handled (corpus miss)?**
  A: Agent returns the engine's soft-failure `explanation` string and can follow up with a Spotify `/search` to find the track by name.
- **Q: In-context vs. ChromaDB for artist facts?**
  A: ChromaDB with lazy ingestion. Wikipedia article bodies can be 10–20k chars; in-context is wasteful and breaks for niche artists.
- **Q: `make train` — is it a blocker for this plan?**
  A: For Steps 1–4 (agent scaffold, tools, graph, RAG) — no. For Step 5 (end-to-end smoke test) — yes. Step 5 explicitly depends on training having run.

---

## Goal

A working LangGraph agent (Phase 3) wired into a Chainlit UI that can answer questions about the user's Spotify listening history and produce content-based recommendations from the corpus. RAG (Wikipedia/Tavily/ChromaDB artist context) is Phase 4 and follows separately.

---

## Approach

Build bottom-up: paths anchor → tools as `StructuredTool` → LangGraph graph → smoke test → Chainlit. Each step independently testable. Key tradeoff: `StructuredTool` wrapping (direct Python calls) over `langchain-mcp-adapters` (MCP subprocess) — same logic, zero process management, tests without a live MCP server. RAG tools are stubbed as no-ops in Phase 3 and filled in Phase 4.

---

## Steps

### Step 0: Bootstrap DB + incremental sync hardening

**Context**: DB is currently empty (`data/listen_wiseer.db` has no tables). All historical data lives in `data/archived/`. The incremental sync logic in `sync.py` is architecturally correct but hits rate limits on large libraries because there is no inter-batch throttle and no time-based guard preventing re-runs within a short window.

**Files**:
- `src/etl/db.py` — add `last_synced TIMESTAMP` column to `playlists` DDL
- `src/spotify/fetch.py` — add 100ms sleep between batches in `fetch_audio_features` and `fetch_artist_features`
- `src/etl/sync.py` — `plan_sync` skips playlists synced within 23h; `upsert_playlists` writes `last_synced`

**Sub-steps** (each independently runnable):

**0a — Bootstrap from archives (zero API calls)**:
```bash
cd projects/listen-wiseer
PYTHONPATH=src uv run python -m etl.bootstrap
```
Expected output: `~2870 tracks, 20 playlists, genre mappings, enriched profiles`.
Validate:
```bash
PYTHONPATH=src uv run python -c "
import duckdb
conn = duckdb.connect('data/listen_wiseer.db')
for t in ['tracks','audio_features','playlists','genre_map','track_profile']:
    n = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'{t}: {n}')
"
```

**0b — Add `last_synced` to schema**:
```python
# src/etl/db.py — add to playlists DDL:
last_synced  TIMESTAMP
# and migration line:
ALTER TABLE playlists ADD COLUMN IF NOT EXISTS last_synced TIMESTAMP;
```

**0c — Inter-batch delay** (100ms between batches):
```python
# src/spotify/fetch.py — in fetch_audio_features and fetch_artist_features loops:
import time
# after each batch response:
time.sleep(0.1)
```

**0d — `plan_sync` respects `last_synced`** (skip if synced within 23h):
```python
# src/etl/sync.py — add to PlaylistSyncItem:
last_synced: datetime | None

@property
def needs_sync(self) -> bool:
    if not self.include_in_refresh:
        return False
    if self.last_synced is not None:
        age_hours = (datetime.now() - self.last_synced).total_seconds() / 3600
        if age_hours < 23:
            return False
    return self.is_new or self.spotify_track_count != self.db_track_count
```

**0e — `upsert_playlists` writes `last_synced`**:
```python
# after track sync completes for a playlist, update last_synced:
conn.execute(
    "UPDATE playlists SET last_synced = NOW() WHERE playlist_id = ?",
    [item.playlist_id]
)
```

**0f — Fix re-auth scope** (audio-features was 403 — likely missing scope, not deprecated for this app):
```python
# src/spotify/auth.py — add to SCOPES:
"user-read-private",   # required for audio-features endpoint
```
Then delete `.spotify_cache` and run `make mcp-server` once to re-authenticate (browser opens, one-time).
After re-auth, re-test audio-features: `client.get("audio-features", ids="<any_track_id>")` should return 200.

**0g — Per-step sync with limits** ✓ DONE 2026-04-03 (safe for testing, prevents blast radius):
```python
# src/etl/sync.py — add limit params to each step:
def sync_tracks(conn, client, items, max_playlists=None, max_tracks=None): ...
def sync_audio_features(conn, client, limit=None): ...
def sync_artist_features(conn, client, limit=None): ...
def sync(conn, client, max_playlists=None, max_tracks=None, limit=None): ...

# main() — add CLI args:
# PYTHONPATH=src uv run python -m etl.sync --playlists 1 --tracks 5
```
Also: `upsert_playlists` should default new-from-Spotify playlists (not in `my_playlists.csv`) to
`include_in_refresh = FALSE` so they don't get swept up automatically.

**0h — Validate each step independently with limits** ✓ DONE 2026-04-03:
```bash
# Test 1: just playlist upsert (no tracks)
PYTHONPATH=src uv run python -m etl.sync --playlists 0
# Test 2: 1 playlist, 5 tracks
PYTHONPATH=src uv run python -m etl.sync --playlists 1 --tracks 5
# Test 3: audio features for 5 tracks
PYTHONPATH=src uv run python -m etl.sync --audio 5
# Test 4: artist features for 5 artists
PYTHONPATH=src uv run python -m etl.sync --artists 5
```

**0i — Cron setup** ✓ DONE 2026-04-04 (macOS launchd):
```bash
# Daily at 02:00. Run after 0h validates.
# Create ~/Library/LaunchAgents/com.wiseer.listen-wiseer-sync.plist
```

**Tests**:
```python
# tests/unit/test_sync_plan.py — add:
from datetime import datetime, timedelta

def test_plan_sync_skips_recently_synced(mock_conn):
    """Playlist synced 1h ago should not need_sync even if counts differ."""
    item = PlaylistSyncItem(
        playlist_id="x", playlist_name="test",
        spotify_track_count=10, db_track_count=8,
        is_new=False, include_in_refresh=True,
        last_synced=datetime.now() - timedelta(hours=1),
    )
    assert not item.needs_sync

def test_plan_sync_syncs_stale_after_24h(mock_conn):
    """Playlist synced 25h ago with count mismatch should need_sync."""
    item = PlaylistSyncItem(
        playlist_id="x", playlist_name="test",
        spotify_track_count=10, db_track_count=8,
        is_new=False, include_in_refresh=True,
        last_synced=datetime.now() - timedelta(hours=25),
    )
    assert item.needs_sync
```

**Done when**: `make init-db` populates DB with ~2870 tracks; `make data-sync` runs without rate limit errors and skips recently-synced playlists; new tests pass.

---

### Step 1: `src/paths.py` + complete training run

**Files**: `src/paths.py` (new), `src/mcp_server/server.py` (lines 22–23), `src/recommend/engine.py` (init, lines ~30–40)

**What**: Add the `src/paths.py` path anchor required by workspace CLAUDE.md convention. Update `server.py` and `engine.py` to import from it instead of computing paths inline. Then run `make train` to completion.

**Snippet**:
```python
# src/paths.py
from __future__ import annotations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent  # src/ → project root
MODELS_DIR = REPO_ROOT / "models"
DATA_DIR = REPO_ROOT / "data"
```

```python
# server.py — replace lines 22–23:
# Before:
_MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "models"
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
# After:
from paths import MODELS_DIR as _MODELS_DIR, DATA_DIR as _DATA_DIR
```

```python
# engine.py __init__ — replace hardcoded Path("models") usage:
# Before (wherever Path("models") appears):
models_dir=Path("models")
# After (callers pass MODELS_DIR from paths):
# engine.py itself doesn't hardcode — callers (server.py, train.py) import from paths
```

**Train run**:
```bash
PYTHONPATH=src uv run python -m recommend.train
ls -lh models/   # expect gmm_corpus.pkl, scaler_corpus.pkl, ~14-32 classifier_*.pkl
```

**Smoke test** (from original PLAN.md Step 11):
```bash
PYTHONPATH=src uv run python -c "
from recommend.engine import RecommendationEngine
from recommend.schemas import RecommendRequest
from paths import MODELS_DIR, DATA_DIR

engine = RecommendationEngine(models_dir=MODELS_DIR, data_dir=DATA_DIR)
for req in [
    RecommendRequest(request_type='track', seed_id='4bJ7tMJqfYmkKgCYzaaG4B', k=5),
    RecommendRequest(request_type='genre', seed_id='zouk', k=5),
    RecommendRequest(request_type='track', seed_id='NONEXISTENT', k=5),
]:
    r = engine.recommend(req)
    print(f'{req.request_type}({req.seed_id}): {len(r.track_uris)} — {r.explanation[:60]}')
"
```

**Test**: `uv run pytest tests/unit/ --tb=short -q`

**Done when**: 190 tests pass; `models/` contains at least `gmm_corpus.pkl`, `scaler_corpus.pkl`, and ≥1 classifier pkl; smoke test prints 3 lines without exception.

---

### Step 2: Agent scaffold — `src/agent/`

**Files**: `src/agent/__init__.py` (new), `src/agent/state.py` (new), `tests/unit/agent/test_state.py` (new), `tests/unit/agent/__init__.py` (new)

**What**: Create the agent package and define `AgentState`. This is the shared state dict that flows through every LangGraph node.

**Snippet**:
```python
# src/agent/state.py
from __future__ import annotations
from typing import Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    intent: str                    # "recommend" | "artist_info" | "history" | "general"
    rewritten_query: str           # query after intent-aware rewrite
    tool_results: list[str]        # raw tool output strings
    context_docs: list[str]        # RAG passages (Phase 4; default [])
```

**Test**:
```python
# tests/unit/agent/test_state.py
from langchain_core.messages import HumanMessage
from agent.state import AgentState

def test_state_construction():
    state: AgentState = {
        "messages": [HumanMessage(content="hello")],
        "intent": "general",
        "rewritten_query": "hello",
        "tool_results": [],
        "context_docs": [],
    }
    assert state["intent"] == "general"
    assert len(state["messages"]) == 1
```

**Run**: `uv run pytest tests/unit/agent/test_state.py -v`

**Done when**: `from agent.state import AgentState` succeeds; test passes.

---

### Step 3: `src/agent/tools.py` — StructuredTool wrappers

**Files**: `src/agent/tools.py` (new), `tests/unit/agent/test_tools.py` (new)

**What**: Wrap the existing Python functions (same ones the MCP server uses) as `StructuredTool` objects. No MCP subprocess. The agent's LLM will see these tools via `bind_tools`.

**Four tool groups**:
1. Recommend tools — call `_engine.recommend()` directly
2. Spotify fetch tools — call `fetch_playlist_tracks`, `fetch_recently_played`, `fetch_artist_features`
3. Artist context tool — Wikipedia + Tavily (implemented in Step 6; stubbed here)
4. Related artists tool — call `SpotifyClient.get` on `/artists/{id}/related-artists`

**Snippet**:
```python
# src/agent/tools.py
from __future__ import annotations
from langchain_core.tools import StructuredTool
from paths import MODELS_DIR, DATA_DIR
from recommend.engine import RecommendationEngine
from recommend.schemas import RecommendRequest

_engine = RecommendationEngine(models_dir=MODELS_DIR, data_dir=DATA_DIR)

def _recommend_similar_tracks(track_id: str, k: int = 10) -> str:
    """Find corpus tracks similar to a given Spotify track ID."""
    result = _engine.recommend(RecommendRequest(request_type="track", seed_id=track_id, k=k))
    if not result.track_uris:
        return result.explanation
    return result.explanation + "\n" + "\n".join(
        f"{i+1}. {n} [spotify:track:{tid}]"
        for i, (n, tid) in enumerate(zip(result.track_names, result.track_ids))
    )

recommend_similar_tracks = StructuredTool.from_function(
    _recommend_similar_tracks,
    name="recommend_similar_tracks",
    description="Find tracks with similar audio characteristics to a Spotify track ID.",
)

# ... same pattern for recommend_for_artist, recommend_by_genre,
#     get_recently_played, get_related_artists
```

**Engine loading**: `tools.py` loads `_engine` at module import time. If models aren't trained, it raises `FileNotFoundError` at import — acceptable; training must precede agent startup.

**Tests** (mock the engine — no pkl load in unit tests):
```python
# tests/unit/agent/test_tools.py
from unittest.mock import MagicMock, patch
from recommend.schemas import RecommendResult

def test_recommend_similar_tracks_returns_string(monkeypatch):
    mock_result = RecommendResult(
        track_uris=["spotify:track:abc"],
        track_ids=["abc"],
        track_names=["Test Track"],
        scores=[0.9],
        pipeline_used="track",
        explanation="Found 1 track",
    )
    with patch("agent.tools._engine") as mock_engine:
        mock_engine.recommend.return_value = mock_result
        from agent.tools import _recommend_similar_tracks
        result = _recommend_similar_tracks("some_id", k=5)
    assert "Test Track" in result

def test_recommend_empty_returns_explanation(monkeypatch):
    mock_result = RecommendResult(
        track_uris=[], track_ids=[], track_names=[], scores=[],
        pipeline_used="track", explanation="Track not in corpus",
    )
    with patch("agent.tools._engine") as mock_engine:
        mock_engine.recommend.return_value = mock_result
        from agent.tools import _recommend_similar_tracks
        result = _recommend_similar_tracks("nonexistent")
    assert result == "Track not in corpus"
```

**Run**: `uv run pytest tests/unit/agent/test_tools.py -v`

**Done when**: All tool wrapper functions importable; unit tests pass with mocked engine.

---

### Step 4: `src/agent/nodes.py` + `src/agent/graph.py` — LangGraph graph

**Files**: `src/agent/nodes.py` (new), `src/agent/graph.py` (new), `tests/unit/agent/test_graph.py` (new)

**What**: Build the custom LangGraph graph. Nodes: `classify_intent` → `call_tools` (ToolNode) → `synthesize`. Routing: intent determines whether to call tools or go straight to synthesis. Use `MemorySaver` for in-session multi-turn memory.

**Graph structure**:
```
START → classify_intent → [route by intent]
    → "tool_call"  → call_tools (ToolNode) → synthesize → END
    → "direct"     → synthesize → END
```

**`classify_intent` node** — LLM call that sets `state["intent"]` and decides whether tools are needed:
```python
# src/agent/nodes.py
from __future__ import annotations
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from agent.state import AgentState
from agent.tools import ALL_TOOLS   # list of all StructuredTool objects
from utils.config import settings

_llm = ChatAnthropic(
    model=settings.anthropic_model,
    api_key=settings.anthropic_api_key,
)
_llm_with_tools = _llm.bind_tools(ALL_TOOLS)

INTENT_SYSTEM = """You are a music assistant. Classify the user's intent and respond.
Intents: recommend (wants track suggestions), artist_info (wants to know about an artist),
history (wants to know about their listening history), general (chat/other).
Use tools when the intent is recommend, artist_info, or history."""

def classify_intent(state: AgentState) -> AgentState:
    messages = [SystemMessage(content=INTENT_SYSTEM)] + state["messages"]
    response = _llm_with_tools.invoke(messages)
    return {"messages": [response]}
```

**`synthesize` node** — final response generation, incorporating tool outputs already in message history:
```python
SYNTH_SYSTEM = """You are listen-wiseer, a personal music assistant.
Summarise the tool results clearly and conversationally.
If recommendations were found, present them as a numbered list with brief notes.
If artist context was retrieved, share the most interesting facts.
Be concise — 3-5 sentences unless the user asked for detail."""

def synthesize(state: AgentState) -> AgentState:
    messages = [SystemMessage(content=SYNTH_SYSTEM)] + state["messages"]
    response = _llm.invoke(messages)
    return {"messages": [response]}
```

**Routing function**:
```python
def route_after_classify(state: AgentState) -> str:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "call_tools"
    return "synthesize"
```

**Graph wiring** (`src/agent/graph.py`):
```python
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from agent.state import AgentState
from agent.nodes import classify_intent, synthesize, route_after_classify, ALL_TOOLS

def build_graph() -> ...:
    builder = StateGraph(AgentState)
    builder.add_node("classify_intent", classify_intent)
    builder.add_node("call_tools", ToolNode(ALL_TOOLS))
    builder.add_node("synthesize", synthesize)

    builder.add_edge(START, "classify_intent")
    builder.add_conditional_edges(
        "classify_intent",
        route_after_classify,
        {"call_tools": "call_tools", "synthesize": "synthesize"},
    )
    builder.add_edge("call_tools", "synthesize")
    builder.add_edge("synthesize", END)

    memory = MemorySaver()
    return builder.compile(checkpointer=memory)

graph = build_graph()
```

**Tests** (mock LLM — no API calls in unit tests):
```python
# tests/unit/agent/test_graph.py
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage

def test_graph_direct_path(monkeypatch):
    """classify_intent returns no tool_calls → goes straight to synthesize."""
    ai_no_tools = AIMessage(content="Here's what I know.", tool_calls=[])
    ai_synth = AIMessage(content="Final answer.")

    with patch("agent.nodes._llm_with_tools") as mock_llm_tools, \
         patch("agent.nodes._llm") as mock_llm, \
         patch("agent.tools._engine"):
        mock_llm_tools.invoke.return_value = ai_no_tools
        mock_llm.invoke.return_value = ai_synth

        from agent.graph import graph
        result = graph.invoke(
            {"messages": [HumanMessage(content="hello")],
             "intent": "", "rewritten_query": "", "tool_results": [], "context_docs": []},
            config={"configurable": {"thread_id": "test-1"}},
        )

    assert result["messages"][-1].content == "Final answer."

def test_graph_tool_path(monkeypatch):
    """classify_intent returns tool_calls → call_tools → synthesize."""
    from langchain_core.messages import AIMessage, ToolMessage
    tool_call = {"name": "recommend_similar_tracks", "args": {"track_id": "abc"}, "id": "tc1"}
    ai_with_tools = AIMessage(content="", tool_calls=[tool_call])
    ai_synth = AIMessage(content="Here are your recommendations.")

    with patch("agent.nodes._llm_with_tools") as mock_llm_tools, \
         patch("agent.nodes._llm") as mock_llm, \
         patch("agent.tools._engine") as mock_engine, \
         patch("agent.tools.recommend_similar_tracks") as mock_tool:
        from recommend.schemas import RecommendResult
        mock_engine.recommend.return_value = RecommendResult(
            track_uris=["spotify:track:abc"], track_ids=["abc"],
            track_names=["Track A"], scores=[0.9], pipeline_used="track",
            explanation="Found 1 track",
        )
        mock_llm_tools.invoke.return_value = ai_with_tools
        mock_llm.invoke.return_value = ai_synth
        mock_tool.invoke.return_value = "Found 1 track\n1. Track A [spotify:track:abc]"

        from agent.graph import graph
        result = graph.invoke(
            {"messages": [HumanMessage(content="recommend tracks like abc")],
             "intent": "", "rewritten_query": "", "tool_results": [], "context_docs": []},
            config={"configurable": {"thread_id": "test-2"}},
        )

    assert len(result["messages"]) > 1
```

**Run**: `uv run pytest tests/unit/agent/test_graph.py -v`

**Done when**: Graph builds without import error; both test paths pass; `from agent.graph import graph` works in a REPL.

---

### Step 5: End-to-end smoke test — agent + tools + engine

**Prerequisite**: `make train` must have completed (all classifiers in `models/`).

**Files**: None changed. This is a validation step only.

**What**: Run the agent with a real LLM call (uses `ANTHROPIC_API_KEY` from `.env`) against the trained engine. No Spotify auth required for track/genre queries.

**Manual smoke test**:
```bash
PYTHONPATH=src uv run python -c "
import asyncio
from langchain_core.messages import HumanMessage
from agent.graph import graph

async def run():
    config = {'configurable': {'thread_id': 'smoke-1'}}
    state = {
        'messages': [HumanMessage(content='Find me 5 tracks similar to bossa nova')],
        'intent': '', 'rewritten_query': '', 'tool_results': [], 'context_docs': [],
    }
    result = await graph.ainvoke(state, config=config)
    print(result['messages'][-1].content)

asyncio.run(run())
"
```

**Expected**: Final message contains a numbered track list or graceful explanation. No exceptions.

**Cost note**: This makes 1–2 Anthropic API calls (~0.01 USD at Haiku rates). Confirm before running.

**Done when**: Agent returns a non-stub response; tool calls visible in LangSmith trace (if enabled) or printed intermediate messages.

---

---

> **Phase 3 ends here. Steps 6–8 are Phase 4 (RAG). Execute after `/compact` and Phase 3 review.**
