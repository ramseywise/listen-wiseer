Revised Phase 3c — LangGraph Agent + Chainlit UI
# Plan: Phase 3c — LangGraph Agent + Chainlit UI
Date: 2026-04-04
Predecessor: Phase 3b (training pipeline)
Next: Phase 4a (RAG + artist context)
---
## Out of Scope
- **Spotify `/recommendations` endpoint** — Phase 4+
- **Last.fm API integration** — deferred; Wikipedia + web search covers the use case
- **Multi-session memory persistence** — `MemorySaver` is in-process only; Redis in Phase 4b
- **FAISS approximate nearest-neighbour** — 200ms scan acceptable for interactive use
- **Assigning ENOA coordinates to new tracks** — corpus tracks only
- **Docker / infra changes** — `infrastructure/` untouched
- **Spotify write operations** — agent recommends; does not write
- **Streaming token output in Chainlit** — `ainvoke` only; streaming is a follow-up
- **RAG (Wikipedia/Tavily/ChromaDB)** — Phase 4a
- **Related artists tool** — Phase 4a (requires new `fetch_related_artists` function)
---
## Goal
A working LangGraph ReAct agent wired into the Chainlit UI that can answer
questions about the user's Spotify listening history and produce content-based
recommendations from the corpus. RAG and artist-context tools are Phase 4a.
---
## Approach
Build bottom-up: tools as `StructuredTool` → ReAct graph → smoke test → Chainlit.
Key decisions:
- **`StructuredTool` wrapping** (direct Python calls) over `langchain-mcp-adapters` —
  zero process management, tests without a live MCP server
- **ReAct loop** (LLM → tools → LLM → ... → END) instead of single-pass —
  supports multi-step queries like "recommend based on my recent listening"
- **Messages-only state** — `AgentState` is just `{messages}`. Additional fields
  (`context_docs`, etc.) added in Phase 4 when RAG needs them
- **Lazy Spotify client** — singleton created on first Spotify tool call, not at
  module import
---
## Steps
### Step 2: Agent scaffold — `src/agent/`
**Files**: `src/agent/__init__.py` (new), `src/agent/state.py` (new),
`tests/unit/agent/__init__.py` (new), `tests/unit/agent/test_state.py` (new)
**What**: Create the agent package and define `AgentState` — the minimal shared
state dict that flows through every LangGraph node.
**Snippet**:
```python
# src/agent/state.py
from __future__ import annotations
from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
Test:

# tests/unit/agent/test_state.py
from langchain_core.messages import HumanMessage
from agent.state import AgentState
def test_state_construction():
    state: AgentState = {"messages": [HumanMessage(content="hello")]}
    assert len(state["messages"]) == 1
def test_state_empty_messages():
    state: AgentState = {"messages": []}
    assert state["messages"] == []
Run: uv run pytest tests/unit/agent/test_state.py -v

Done when: from agent.state import AgentState succeeds; test passes.

Step 3: src/agent/tools.py — StructuredTool wrappers
Files: src/agent/tools.py (new), tests/unit/agent/test_tools.py (new)

What: Wrap existing Python functions as StructuredTool objects. The agent's LLM sees these via bind_tools. No MCP subprocess.

Six tools for Phase 3c:

recommend_similar_tracks — engine.recommend(type="track")
recommend_for_artist — engine.recommend(type="artist")
recommend_by_genre — engine.recommend(type="genre")
recommend_for_playlist — engine.recommend(type="playlist")
get_recently_played — fetch_recently_played(client, limit)
search_tracks — SpotifyClient.search(query, limit)
Engine loading: Module-level with try/except FileNotFoundError → _engine = None (same pattern as mcp_server/server.py). Each recommend tool checks if _engine is None and returns an explanatory string.

Spotify client: Lazy singleton via _get_client():

_client: SpotifyClient | None = None
def _get_client() -> SpotifyClient:
    global _client
    if _client is None:
        _client = SpotifyClient()
    return _client
Result formatting: _format_result(result: RecommendResult) -> str helper (same logic as MCP server's _format_result).

Snippet:

# src/agent/tools.py
from __future__ import annotations
from langchain_core.tools import StructuredTool
from paths import MODELS_DIR, DATA_DIR
from recommend.engine import RecommendationEngine
from recommend.schemas import RecommendRequest
from spotify.client import SpotifyClient
from spotify.fetch import fetch_recently_played
from utils.logging import get_logger
log = get_logger(__name__)
# --- Engine (eager, fail-soft) ---
try:
    _engine = RecommendationEngine(models_dir=MODELS_DIR, data_dir=DATA_DIR)
except FileNotFoundError:
    _engine = None
    log.warning("agent.tools.engine_unavailable")
# --- Spotify client (lazy) ---
_client: SpotifyClient | None = None
def _get_client() -> SpotifyClient:
    global _client
    if _client is None:
        _client = SpotifyClient()
    return _client
def _format_result(result) -> str:
    if not result.track_uris:
        return result.explanation
    lines = [result.explanation]
    for i, (name, tid) in enumerate(zip(result.track_names, result.track_ids)):
        lines.append(f"{i+1}. {name} [spotify:track:{tid}]")
    return "\n".join(lines)
# --- Recommend tools ---
def _recommend_similar_tracks(track_id: str, k: int = 10) -> str:
    """Find corpus tracks similar to a given Spotify track ID."""
    if _engine is None:
        return "Recommendation engine not available — models not trained."
    return _format_result(
        _engine.recommend(RecommendRequest(request_type="track", seed_id=track_id, k=k))
    )
recommend_similar_tracks = StructuredTool.from_function(
    _recommend_similar_tracks,
    name="recommend_similar_tracks",
    description="Find tracks with similar audio characteristics to a Spotify track ID.",
)
# ... same pattern for recommend_for_artist, recommend_by_genre, recommend_for_playlist
# --- Spotify tools ---
def _get_recently_played(limit: int = 20) -> str:
    """Get the user's recently played tracks from Spotify."""
    try:
        tracks = fetch_recently_played(_get_client(), limit=limit)
        if not tracks:
            return "No recently played tracks found."
        return "\n".join(
            f"{i+1}. {t.track_name} by {t.artist_name} [{t.track_id}]"
            for i, t in enumerate(tracks)
        )
    except Exception as exc:
        return f"Failed to fetch recently played: {exc}"
get_recently_played_tool = StructuredTool.from_function(
    _get_recently_played,
    name="get_recently_played",
    description="Get the user's recently played tracks from Spotify.",
)
# ... same pattern for search_tracks
ALL_TOOLS = [
    recommend_similar_tracks,
    recommend_for_artist,
    recommend_by_genre,
    recommend_for_playlist,
    get_recently_played_tool,
    search_tracks_tool,
]
Tests (mock engine + client — no pkl load or Spotify auth in unit tests):

# tests/unit/agent/test_tools.py
from unittest.mock import MagicMock, patch
from recommend.schemas import RecommendResult
@patch("agent.tools._engine")
def test_recommend_similar_tracks_formats_result(mock_engine):
    mock_engine.recommend.return_value = RecommendResult(
        track_uris=["spotify:track:abc"], track_ids=["abc"],
        track_names=["Test Track"], scores=[0.9],
        pipeline_used="track", explanation="Found 1 track",
    )
    from agent.tools import _recommend_similar_tracks
    result = _recommend_similar_tracks("some_id", k=5)
    assert "Test Track" in result
@patch("agent.tools._engine", None)
def test_recommend_engine_unavailable():
    from agent.tools import _recommend_similar_tracks
    result = _recommend_similar_tracks("any_id")
    assert "not available" in result
@patch("agent.tools._get_client")
def test_get_recently_played_formats_tracks(mock_get_client):
    from utils.schemas import TrackFeatures
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    # ... mock fetch_recently_played to return synthetic tracks
Run: uv run pytest tests/unit/agent/test_tools.py -v

Done when: All tool wrappers importable; unit tests pass with mocked deps.

Step 4: ReAct graph — src/agent/nodes.py + src/agent/graph.py
Files: src/agent/nodes.py (new), src/agent/graph.py (new), tests/unit/agent/test_graph.py (new)

What: Build a ReAct loop graph. The LLM decides when to call tools and when to produce a final answer. Bounded by settings.max_agent_iterations via recursion_limit.

Graph structure:

START → agent_node (LLM with tools bound)
    → [route_after_agent]
        → has tool_calls → call_tools (ToolNode) → agent_node  (loop)
        → no tool_calls  → END
agent_node — single LLM call with system prompt + tools:

# src/agent/nodes.py
from __future__ import annotations
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from agent.state import AgentState
from agent.tools import ALL_TOOLS
from utils.config import settings
_llm = ChatAnthropic(
    model=settings.anthropic_model,
    api_key=settings.anthropic_api_key,
)
_llm_with_tools = _llm.bind_tools(ALL_TOOLS)
SYSTEM_PROMPT = """You are listen-wiseer, a personal music assistant.
You help users explore their Spotify listening history, discover new music through
content-based recommendations, and learn about artists.
When recommending tracks:
- Use recommend_similar_tracks for "find tracks like X"
- Use recommend_for_artist for "recommend tracks by/like artist X"
- Use recommend_by_genre for genre-based requests (e.g. "zouk", "bossa nova")
- Use recommend_for_playlist for playlist-based recommendations
- Use get_recently_played to see what the user has been listening to
- Use search_tracks to find a specific track or artist on Spotify
Present recommendations as a numbered list with brief notes.
Be concise — 3-5 sentences unless the user asks for detail.
If a tool returns no results, explain why and suggest alternatives."""
def agent_node(state: AgentState) -> AgentState:
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = _llm_with_tools.invoke(messages)
    return {"messages": [response]}
def route_after_agent(state: AgentState) -> str:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "call_tools"
    return "__end__"
Graph wiring (src/agent/graph.py):

# src/agent/graph.py
from __future__ import annotations
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from agent.state import AgentState
from agent.nodes import agent_node, route_after_agent
from agent.tools import ALL_TOOLS
from utils.config import settings
def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("call_tools", ToolNode(ALL_TOOLS))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        route_after_agent,
        {"call_tools": "call_tools", "__end__": END},
    )
    builder.add_edge("call_tools", "agent")  # loop back
    memory = MemorySaver()
    return builder.compile(
        checkpointer=memory,
        recursion_limit=settings.max_agent_iterations * 2,  # each iteration = 2 nodes
    )
graph = build_graph()
Tests (mock LLM — no API calls):

# tests/unit/agent/test_graph.py
from unittest.mock import patch
from langchain_core.messages import HumanMessage, AIMessage
@patch("agent.nodes._llm_with_tools")
@patch("agent.tools._engine")
def test_graph_direct_response(mock_engine, mock_llm):
    """No tool_calls → straight to END."""
    mock_llm.invoke.return_value = AIMessage(content="Hello!", tool_calls=[])
    from agent.graph import build_graph
    g = build_graph()
    result = g.invoke(
        {"messages": [HumanMessage(content="hello")]},
        config={"configurable": {"thread_id": "t1"}},
    )
    assert result["messages"][-1].content == "Hello!"
@patch("agent.nodes._llm_with_tools")
@patch("agent.tools._engine")
def test_graph_tool_then_response(mock_engine, mock_llm):
    """tool_calls → call_tools → agent → END."""
    tool_call = {"name": "recommend_by_genre", "args": {"genre_name": "zouk"}, "id": "tc1"}
    call1 = AIMessage(content="", tool_calls=[tool_call])
    call2 = AIMessage(content="Here are your recommendations.", tool_calls=[])
    mock_llm.invoke.side_effect = [call1, call2]
    # ... mock tool execution
    from agent.graph import build_graph
    g = build_graph()
    result = g.invoke(
        {"messages": [HumanMessage(content="recommend zouk tracks")]},
        config={"configurable": {"thread_id": "t2"}},
    )
    assert "recommendations" in result["messages"][-1].content.lower()
def test_multiturn_memory():
    """Two invocations with same thread_id share message history."""
    # ... invoke twice, assert second invocation sees first turn's messages
Run: uv run pytest tests/unit/agent/test_graph.py -v

Done when: Graph builds; both test paths pass; from agent.graph import graph works.

Step 5: End-to-end smoke test
Prerequisite: make train completed (classifiers in models/).

Files: None changed. Validation only.

What: Run the agent with a real LLM call against the trained engine.

Manual smoke test:

PYTHONPATH=src uv run python -c "
from langchain_core.messages import HumanMessage
from agent.graph import graph
result = graph.invoke(
    {'messages': [HumanMessage(content='Find me 5 tracks similar to bossa nova')]},
    config={'configurable': {'thread_id': 'smoke-1'}},
)
print(result['messages'][-1].content)
"
Expected: Final message contains a numbered track list or graceful explanation.

Cost note: 1-3 Anthropic API calls (~$0.01 at Haiku rates). Confirm before running.

Done when: Agent returns a real response; tool calls visible in message history.

Step 6: Chainlit wiring —
Files:
 (replace stub)

What: Replace the echo stub with graph.ainvoke. Maintain per-session thread ID via cl.user_session. No streaming tokens (deferred).

Snippet:

# src/app/main.py
from __future__ import annotations
import uuid
import chainlit as cl
from langchain_core.messages import HumanMessage
from agent.graph import graph
from utils.logging import get_logger
log = get_logger(__name__)
@cl.on_chat_start
async def start():
    thread_id = str(uuid.uuid4())
    cl.user_session.set("thread_id", thread_id)
    log.info("app.session_start", thread_id=thread_id)
    await cl.Message(
        content=(
            "Welcome to **listen-wiseer**!\n\n"
            "Ask me about your Spotify listening history, "
            "get recommendations, or learn about an artist."
        )
    ).send()
@cl.on_message
async def on_message(message: cl.Message):
    thread_id = cl.user_session.get("thread_id")
    config = {"configurable": {"thread_id": thread_id}}
    state = {"messages": [HumanMessage(content=message.content)]}
    try:
        result = await graph.ainvoke(state, config=config)
        reply = result["messages"][-1].content
    except Exception as exc:
        log.error("app.on_message.failed", error=str(exc), thread_id=thread_id)
        reply = "Something went wrong — please try again."
    await cl.Message(content=reply).send()
Manual test:

make app
# Open http://localhost:8000
# Send: "recommend me some zouk tracks"
# Expected: numbered track list, not "[stub] received: ..."
# Send: "now find something more mellow" (tests multi-turn via same thread_id)
Done when: Chainlit UI starts; messages route through agent; multi-turn works.

Test Plan
Step	Test command	Verifies
2	uv run pytest tests/unit/agent/test_state.py -v	AgentState construction
3	uv run pytest tests/unit/agent/test_tools.py -v	Tool wrappers, format, fail-soft
4	uv run pytest tests/unit/agent/test_graph.py -v	ReAct routing: direct + tool paths
5	Manual smoke (see above)	Live LLM + engine end-to-end
6	make app + manual	Chainlit → agent → response
Full regression after each step: uv run pytest tests/unit/ --tb=short -q

Risks & Rollback
Step 3: Tool import fails if models missing
Mitigation: try/except FileNotFoundError → _engine = None; each tool returns string
Rollback: git revert HEAD --no-edit
Step 4: ReAct loop runs away
Mitigation: recursion_limit from config (max_agent_iterations * 2)
Rollback: Lower max_agent_iterations in .env
Step 4: MemorySaver thread_id collision in tests
Mitigation: Unique thread_id per test (uuid4 or test name)
Step 5: LLM doesn't call tools for genre queries
Mitigation: Tune system prompt; explicit tool-use instructions
Rollback: Prompt-only change in nodes.py
Step 6: Sync tools block event loop in Chainlit
Mitigation: LangGraph's ToolNode already wraps sync calls via run_in_executor
Fallback: Wrap with asyncio.to_thread if needed
Global rollback
git revert HEAD~N..HEAD --no-edit
uv run pytest tests/unit/ --tb=short -q
Dependency map
Step 2 (AgentState)
  ↓
Step 3 (tools.py) ← needs MODELS_DIR from paths.py (Phase 3b ✓)
  ↓
Step 4 (graph.py) ← needs Steps 2 + 3
  ↓
Step 5 (smoke test) ← needs Step 4 + trained models (Phase 3b ✓)
  ↓
Step 6 (Chainlit) ← needs Step 4

---

Now Phase 4a:

```markdown
# Plan: Phase 4a — RAG + Artist Context Tools
Date: 2026-04-04
Predecessor: Phase 3c (agent + Chainlit)
Next: Phase 4b (long-term memory)

---

## Out of Scope

- **Long-term memory / Redis checkpointer** — Phase 4b
- **Episodic / semantic / procedural memory** — Phase 4b
- **Eval framework** — Phase 5
- **Streamlit dashboard** — Phase 6
- **Tavily as primary source** — Wikipedia primary, Tavily fallback only
- **Pre-populating ChromaDB** — lazy ingestion on first query per artist

---

## Goal

Add artist-context RAG (Wikipedia + Tavily → ChromaDB) and a related-artists
Spotify tool to the existing ReAct agent. After this phase, the agent can
answer "who is Aphex Twin?" and "who sounds like Radiohead?" with real data.

---

## Steps

### Step 1: `src/agent/rag.py` — Wikipedia + Tavily + ChromaDB

**Files**: `src/agent/rag.py` (new), `tests/unit/agent/test_rag.py` (new),
`.env.example` (add `TAVILY_API_KEY`), `src/utils/config.py` (add `tavily_api_key`)

**Prerequisites**: Check if `tavily-python` and `wikipedia` are already deps;
`uv add` if not.

**What**: Lazy-ingestion ChromaDB RAG. Single `"artist_info"` collection.
On cache miss: fetch Wikipedia (primary) or Tavily search (fallback for niche
artists), chunk, embed with `all-MiniLM-L6-v2`, upsert. Return top-k passages.

**Key functions**:
- `get_artist_context(artist_name: str, top_k: int = 3) -> str` — public API
- `_fetch_wikipedia(artist_name: str) -> str | None` — Wikipedia fetch with
  `DisambiguationError` handling
- `_fetch_tavily(artist_name: str) -> str | None` — Tavily fallback (skipped
  if no API key)
- `_chunk_text(text: str) -> list[str]` — overlapping character chunks (~400 tokens)
- `_ingest(artist_name: str, text: str) -> None` — embed + upsert to ChromaDB

**ChromaDB path**: Anchored via `REPO_ROOT / settings.chroma_persist_directory`
(already configured in `utils/config.py`).

**Embedding model**: `settings.embedding_model` (default: `all-MiniLM-L6-v2`,
already configured).

**Tests** (mock Wikipedia + Tavily — no network in unit tests):
```python
def test_get_artist_context_wikipedia_hit(tmp_path, monkeypatch):
    # Mock _fetch_wikipedia to return text, mock ChromaDB collection
    # Assert: returns non-empty string, _fetch_wikipedia called once

def test_get_artist_context_tavily_fallback(tmp_path, monkeypatch):
    # Mock _fetch_wikipedia → None, _fetch_tavily → text
    # Assert: Tavily fallback activated

def test_chunk_text_creates_overlapping_chunks():
    text = "a" * 2000
    chunks = _chunk_text(text)
    assert len(chunks) > 1
Run: uv run pytest tests/unit/agent/test_rag.py -v

Done when: Unit tests pass; get_artist_context("Aphex Twin") returns non-empty string in a REPL (requires internet).

Step 2: Wire RAG tool into agent
Files: src/agent/tools.py (add tool), src/agent/nodes.py (update system prompt)

What: Add get_artist_context as a StructuredTool. Add to ALL_TOOLS. Graph picks it up automatically (ToolNode uses the list). Update system prompt to mention the new tool.

Snippet:

# src/agent/tools.py — add:
from agent.rag import get_artist_context as _get_artist_context
get_artist_context_tool = StructuredTool.from_function(
    _get_artist_context,
    name="get_artist_context",
    description=(
        "Retrieve biographical info and interesting facts about a musician or band. "
        "Use when the user asks who an artist is, what they're known for, or wants trivia."
    ),
)
ALL_TOOLS.append(get_artist_context_tool)
System prompt addition (nodes.py):

- Use get_artist_context for "who is X?", "tell me about X", artist trivia
Test:

def test_artist_context_tool_in_all_tools():
    from agent.tools import ALL_TOOLS
    names = [t.name for t in ALL_TOOLS]
    assert "get_artist_context" in names
Run: uv run pytest tests/unit/agent/ -v

Done when: ALL_TOOLS contains 7 tools; smoke test with "who is Aphex Twin?" routes to get_artist_context.

Step 3: Related artists tool — new Spotify fetch + agent tool
Files:
 (add fetch_related_artists), src/agent/tools.py (add tool), tests/unit/agent/test_tools.py (extend),
 (extend)

What: Add fetch_related_artists(client, artist_id) to fetch.py. Wrap as StructuredTool in tools.py. Fills the "who sounds like X?" gap.

Snippet:

# src/spotify/fetch.py
def fetch_related_artists(client: SpotifyClient, artist_id: str) -> list[dict]:
    """Fetch up to 20 related artists for a given artist ID."""
    response = client.get(f"artists/{artist_id}/related-artists")
    artists = response.get("artists", [])
    log.info("spotify.fetch_related_artists", artist_id=artist_id, n=len(artists))
    return [
        {"id": a["id"], "name": a["name"], "genres": a.get("genres", [])}
        for a in artists
    ]
# src/agent/tools.py
def _get_related_artists(artist_id: str) -> str:
    """Find artists similar to a given Spotify artist ID."""
    try:
        artists = fetch_related_artists(_get_client(), artist_id)
        if not artists:
            return f"No related artists found for {artist_id}"
        return "\n".join(
            f"- {a['name']} ({', '.join(a['genres'][:3]) or 'unknown genre'})"
            for a in artists
        )
    except Exception as exc:
        return f"Failed to fetch related artists: {exc}"
get_related_artists_tool = StructuredTool.from_function(...)
ALL_TOOLS.append(get_related_artists_tool)
Tests:

def test_fetch_related_artists_empty():
    mock_client = MagicMock()
    mock_client.get.return_value = {"artists": []}
    result = fetch_related_artists(mock_client, "some_id")
    assert result == []
def test_get_related_artists_formats_output():
    # Mock _get_client + fetch_related_artists → list of dicts
    # Assert formatted string with artist names
Run: uv run pytest tests/unit/agent/test_tools.py tests/unit/test_spotify_client.py -v

Done when: ALL_TOOLS contains 8 tools; fetch_related_artists tested.

Step 4: End-to-end validation
Files: None. Manual validation.

Smoke tests:

"who is Aphex Twin?" → get_artist_context → Wikipedia passages
"who sounds like Radiohead?" → search_tracks (find artist ID) → get_related_artists → list of similar artists
"recommend zouk tracks" → recommend_by_genre → numbered list (Phase 3c still works)
Cost note: 2-4 Anthropic API calls + potential Wikipedia/Tavily fetches. Confirm before running.

Done when: All three query types produce useful responses in Chainlit.

Test Plan
Step	Test command	Verifies
1	uv run pytest tests/unit/agent/test_rag.py -v	RAG fetch/chunk/ingest (mocked)
2	uv run pytest tests/unit/agent/ -v	RAG tool wired; all agent tests pass
3	uv run pytest tests/unit/agent/test_tools.py tests/unit/test_spotify_client.py -v	Related artists fetch + tool
4	make app + manual	Full end-to-end in Chainlit
Full regression: uv run pytest tests/unit/ --tb=short -q

Dependency map
Step 1 (rag.py) ← independent; needs chromadb + sentence-transformers (already installed)
  ↓
Step 2 (wire RAG tool) ← needs Step 1 + Phase 3c tools.py
  ↓
Step 3 (related artists) ← needs Phase 3c tools.py (independent of Step 1-2)
  ↓
Step 4 (validation) ← needs Steps 1-3

---

The existing `phase4_memory.md` (Steps 4.1–4.7: Redis, episodic, semantic, procedural memory, optimizer, history trim) stays as-is — that becomes **Phase 4b**. Similarly `phase5_eval.md` and `phase6_dashboard.md` are unchanged.
