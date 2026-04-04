# Plan: Phase 3c — LangGraph Agent + Chainlit UI
Date: 2026-04-03
Predecessor: Phase 3b (training pipeline)
Next: Phase 4 (RAG)

---

## Out of Scope

- **Spotify `/recommendations` endpoint** — Phase 4+
- **Last.fm API integration** — deferred; Wikipedia + web search covers the use case
- **Multi-session memory persistence** — `MemorySaver` is in-process only
- **FAISS approximate nearest-neighbour** — 200ms scan acceptable for interactive use
- **Assigning ENOA coordinates to new tracks** — corpus tracks only
- **Docker / infra changes** — `infrastructure/` untouched
- **Spotify write operations** — agent recommends; does not write
- **Streaming token output in Chainlit** — Step 9 uses `ainvoke`; streaming is a follow-up

---

## Goal

A working LangGraph agent wired into a Chainlit UI that can answer questions about the user's Spotify listening history and produce content-based recommendations from the corpus. RAG tools are stubbed as no-ops here and filled in Phase 4.

---

## Approach

Build bottom-up: tools as `StructuredTool` → LangGraph graph → smoke test → Chainlit. Key tradeoff: `StructuredTool` wrapping (direct Python calls) over `langchain-mcp-adapters` — zero process management, tests without a live MCP server.

---

## Steps

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
