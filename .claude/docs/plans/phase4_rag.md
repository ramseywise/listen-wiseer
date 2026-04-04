# Plan: Phase 4 — RAG (Wikipedia + Tavily + ChromaDB)
Date: 2026-04-03
Based on: research/infra_support.md

> Prerequisite: Phase 3 complete. Execute after `/compact` and Phase 3 review.

---

### Step 6: RAG — `src/agent/rag.py` — Wikipedia + Tavily artist context

**Files**: `src/agent/rag.py` (new), `tests/unit/agent/test_rag.py` (new), `.env.example` (add `TAVILY_API_KEY`), `src/utils/config.py` (add `tavily_api_key`)

**Prerequisites**: `uv add tavily-python` (check if already installed first).

**What**: Implement lazy-ingestion ChromaDB RAG. A single `"artist_info"` collection. On cache miss: fetch Wikipedia (primary) or Tavily search (fallback for niche artists), chunk, embed with `all-MiniLM-L6-v2`, upsert. Return top-k passages.

**Snippet**:
```python
# src/agent/rag.py
from __future__ import annotations
import chromadb
from sentence_transformers import SentenceTransformer
from paths import REPO_ROOT
from utils.config import settings

_CHUNK_SIZE = 400      # tokens ~ chars/4
_CHUNK_OVERLAP = 50
_COLLECTION = "artist_info"

_chroma = chromadb.PersistentClient(
    path=str(REPO_ROOT / settings.chroma_persist_directory.lstrip("./")),
)
_embedder = SentenceTransformer(settings.embedding_model)
_collection = _chroma.get_or_create_collection(_COLLECTION)


def get_artist_context(artist_name: str, top_k: int = 3) -> str:
    """Return top_k relevant passages about artist_name from cache or live fetch."""
    # 1. query ChromaDB
    # 2. if results below threshold: fetch + ingest
    # 3. return formatted passages
    ...

def _fetch_wikipedia(artist_name: str) -> str | None:
    """Return page content or None if not found / too short."""
    import wikipedia
    try:
        results = wikipedia.search(artist_name, results=3)
        if not results:
            return None
        page = wikipedia.page(results[0], auto_suggest=False)
        return page.content
    except Exception:
        return None

def _fetch_tavily(artist_name: str) -> str | None:
    """Fallback: Tavily web search for artist bio."""
    if not settings.tavily_api_key:
        return None
    from tavily import TavilyClient
    client = TavilyClient(api_key=settings.tavily_api_key)
    resp = client.search(f"{artist_name} musician biography interesting facts", max_results=3)
    return "\n\n".join(r["content"] for r in resp.get("results", []))

def _chunk_text(text: str) -> list[str]:
    """Split text into overlapping character-based chunks (~400 tokens)."""
    size = _CHUNK_SIZE * 4   # chars
    step = (_CHUNK_SIZE - _CHUNK_OVERLAP) * 4
    return [text[i : i + size] for i in range(0, len(text), step) if text[i : i + size].strip()]

def _ingest(artist_name: str, text: str) -> None:
    chunks = _chunk_text(text)
    if not chunks:
        return
    embeddings = _embedder.encode(chunks).tolist()
    ids = [f"{artist_name}::{i}" for i in range(len(chunks))]
    _collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=[{"artist": artist_name}] * len(chunks),
    )
```

**Config addition** (`src/utils/config.py`):
```python
# Add to Settings:
tavily_api_key: str = ""
```

**Tests** (mock Wikipedia and Tavily — no network in unit tests):
```python
# tests/unit/agent/test_rag.py
from unittest.mock import patch, MagicMock

def test_get_artist_context_wikipedia_hit(tmp_path, monkeypatch):
    """Cache miss → Wikipedia fetch → returns passages."""
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", str(tmp_path / "chroma"))
    with patch("agent.rag._fetch_wikipedia", return_value="Aphex Twin is ...") as mock_wiki, \
         patch("agent.rag._collection") as mock_col:
        mock_col.query.return_value = {"documents": [[]], "distances": [[]]}
        mock_col.upsert = MagicMock()
        from agent.rag import get_artist_context
        result = get_artist_context("Aphex Twin", top_k=2)
    mock_wiki.assert_called_once_with("Aphex Twin")
    assert isinstance(result, str)

def test_chunk_text_creates_overlapping_chunks():
    from agent.rag import _chunk_text
    text = "a" * 2000
    chunks = _chunk_text(text)
    assert len(chunks) > 1
```

**Run**: `uv run pytest tests/unit/agent/test_rag.py -v`

**Done when**: `get_artist_context("Aphex Twin")` returns non-empty string in a REPL (requires internet); unit tests pass with mocks.

---

### Step 7: [Phase 4] Wire RAG into agent tools + graph

**Files**: `src/agent/tools.py` (add `get_artist_context_tool`), `src/agent/graph.py` (add tool to `ALL_TOOLS`)

**What**: Add `get_artist_context` as a `StructuredTool` so the agent can invoke it when intent is `artist_info`. Update `ALL_TOOLS` list and rebuild graph. No node changes needed — `ToolNode` picks up new tools automatically.

**Snippet**:
```python
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

ALL_TOOLS = [
    recommend_similar_tracks,
    recommend_for_artist,
    recommend_by_genre,
    get_recently_played_tool,
    get_related_artists_tool,
    get_artist_context_tool,   # ← new
]
```

**Test** (extend `test_tools.py`):
```python
def test_get_artist_context_tool_callable():
    with patch("agent.rag._collection") as mock_col, \
         patch("agent.rag._fetch_wikipedia", return_value="Facts..."):
        mock_col.query.return_value = {"documents": [[]], "distances": [[]]}
        mock_col.upsert = MagicMock()
        from agent.tools import get_artist_context_tool
        result = get_artist_context_tool.invoke({"artist_name": "Miles Davis"})
    assert isinstance(result, str)
```

**Run**: `uv run pytest tests/unit/agent/ -v`

**Done when**: `ALL_TOOLS` contains 6 tools; `graph.ainvoke` with "who is Aphex Twin?" routes to `get_artist_context` (visible in message history).

---

### Step 8: [Phase 4] Related artists tool — new Spotify fetch function

**Files**: `src/spotify/fetch.py` (add `fetch_related_artists`), `src/agent/tools.py` (add `get_related_artists_tool`), `tests/unit/test_spotify_client.py` (extend)

**What**: Add `fetch_related_artists(client, artist_id)` to `fetch.py`. Wrap as a tool in `tools.py`. This fills the RESEARCH.md gap for "who sounds like X?" queries.

**Snippet**:
```python
# src/spotify/fetch.py — add:
def fetch_related_artists(client: SpotifyClient, artist_id: str) -> list[dict]:
    """Fetch up to 20 related artists for a given artist ID."""
    response = client.get(f"artists/{artist_id}/related-artists")
    artists = response.get("artists", [])
    log.info("spotify.fetch_related_artists", artist_id=artist_id, n=len(artists))
    return [{"id": a["id"], "name": a["name"], "genres": a.get("genres", [])} for a in artists]
```

```python
# src/agent/tools.py — add:
from spotify.fetch import fetch_related_artists as _fetch_related_artists

def _get_related_artists(artist_id: str) -> str:
    """Find artists that sound similar to a given Spotify artist ID."""
    sp = SpotifyClient()
    artists = _fetch_related_artists(sp, artist_id)
    if not artists:
        return f"No related artists found for {artist_id}"
    return "\n".join(f"- {a['name']} ({', '.join(a['genres'][:2]) or 'unknown genre'})" for a in artists)

get_related_artists_tool = StructuredTool.from_function(
    _get_related_artists,
    name="get_related_artists",
    description="Find artists that sound similar to a Spotify artist ID. Use for 'who sounds like X?' queries.",
)
```

**Test**:
```python
# tests/unit/test_spotify_client.py — add:
def test_fetch_related_artists_empty_response(monkeypatch):
    from unittest.mock import MagicMock
    from spotify.fetch import fetch_related_artists
    mock_client = MagicMock()
    mock_client.get.return_value = {"artists": []}
    result = fetch_related_artists(mock_client, "some_artist_id")
    assert result == []
```

**Run**: `uv run pytest tests/unit/test_spotify_client.py -v`

**Done when**: `fetch_related_artists` importable and tested; tool in `ALL_TOOLS`.

---

### Step 9: Connect Chainlit — `src/app/main.py`

**Files**: `src/app/main.py` (replace stub)

**What**: Replace the `[stub]` handler with a real `graph.ainvoke` call. Maintain per-session thread ID using `cl.user_session`. No streaming tokens (deferred to Out of Scope).

**Snippet**:
```python
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
    cl.user_session.set("thread_id", str(uuid.uuid4()))
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
    state = {
        "messages": [HumanMessage(content=message.content)],
        "intent": "",
        "rewritten_query": "",
        "tool_results": [],
        "context_docs": [],
    }
    try:
        result = await graph.ainvoke(state, config=config)
        reply = result["messages"][-1].content
    except Exception as exc:
        log.error("app.on_message.error", error=str(exc))
        reply = "Something went wrong — please try again."
    await cl.Message(content=reply).send()
```

**Manual test**:
```bash
PYTHONPATH=src uv run chainlit run src/app/main.py
# Open http://localhost:8000
# Send: "recommend me some zouk tracks"
# Expected: numbered list of tracks, not "[stub] received: ..."
```

**Done when**: Chainlit UI starts without error; first user message returns a non-stub response from the agent.

---

## Test Plan

| Step | Test command | What it verifies |
|------|-------------|-----------------|
| 1 | `uv run pytest tests/unit/ --tb=short -q` | Existing 190 tests still pass after paths.py change |
| 2 | `uv run pytest tests/unit/agent/test_state.py -v` | AgentState constructs correctly |
| 3 | `uv run pytest tests/unit/agent/test_tools.py -v` | Tool wrappers return strings; handle empty results |
| 4 | `uv run pytest tests/unit/agent/test_graph.py -v` | Both routing paths (direct + tool) work with mocked LLM |
| 5 | Manual smoke (see Step 5) | Live LLM call; real engine; end-to-end |
| 6 | `uv run pytest tests/unit/agent/test_rag.py -v` | Wikipedia fetch + chunking + ChromaDB upsert (mocked) |
| 7 | `uv run pytest tests/unit/agent/ -v` | All agent tests including RAG tool wiring |
| 8 | `uv run pytest tests/unit/test_spotify_client.py -v` | `fetch_related_artists` handles empty response |
| 9 | `PYTHONPATH=src uv run chainlit run src/app/main.py` | UI starts; messages route through agent |

**Full regression after each step**:
```bash
uv run pytest tests/unit/ --tb=short -q
```

---

## Risks & Rollback

### Step 1: paths.py + training run
- **Risk**: `make train` interrupted again (e.g. OOM at 595k rows). Leaves partial classifiers in `models/`.
- **Blast radius**: Local. Engine will load with fewer classifiers; playlist pipeline may soft-fail for missing ones.
- **Rollback**: Re-run `make train` — `train.py` skips playlists with < 20 positives and saves each pkl independently. No full rerun needed; just re-run and it will fill gaps.
- **Verify rollback**: `ls models/classifier_*.pkl | wc -l` — count increases.

- **Risk**: `paths.py` import breaks `server.py` or `engine.py` if `PYTHONPATH` doesn't include `src/`.
- **Blast radius**: Local. Only affects startup; no data touched.
- **Rollback**: `git checkout src/mcp_server/server.py src/recommend/engine.py` — restores inline paths.
- **Verify rollback**: `uv run pytest tests/unit/ --tb=short -q` passes.

### Step 2: Agent scaffold
- **Risk**: `AgentState` TypedDict key mismatch causes `KeyError` in nodes (e.g. node returns `intent` but state doesn't define it).
- **Blast radius**: Local. Fails at runtime in Step 4.
- **Rollback**: `git revert HEAD --no-edit` (only `src/agent/` files touched).
- **Verify rollback**: `uv run pytest tests/unit/agent/test_state.py` passes or dir is gone.

### Step 3: Tool wrappers
- **Risk**: `_engine` loaded at `tools.py` import time — if `models/` is incomplete, entire agent fails to import.
- **Blast radius**: Local. Blocks Steps 4–9.
- **Mitigation**: Same `try/except FileNotFoundError` pattern as `server.py`; set `_engine = None` and have each tool return an explanatory string.
- **Rollback**: `git revert HEAD --no-edit`
- **Verify rollback**: `from agent import tools` no longer errors.

### Step 4: LangGraph graph
- **Risk**: Conditional edge routing returns a key not in the edge map — LangGraph raises `ValueError` at compile time.
- **Blast radius**: Local. Agent fails to build.
- **Rollback**: `git revert HEAD --no-edit`
- **Verify rollback**: `from agent.graph import graph` raises no error.

- **Risk**: `MemorySaver` thread ID collision in tests — two tests sharing the same `thread_id` will bleed state.
- **Blast radius**: Local. Tests may fail non-deterministically.
- **Mitigation**: Use unique `thread_id` per test (`uuid4()` or test name).
- **Rollback**: Fix test fixtures — not a code rollback.

### Step 5: Live smoke test
- **Risk**: LLM returns no tool calls for a genre query — agent goes to `synthesize` directly with no recommendations.
- **Blast radius**: User-visible (incorrect behaviour). Not a crash.
- **Mitigation**: Check `INTENT_SYSTEM` prompt; ensure genre queries are unambiguous enough to trigger tool call.
- **Rollback**: No code change needed — tune system prompt in `nodes.py`.

### Step 6: RAG
- **Risk**: `chromadb.PersistentClient` creates `data/vectorstore/` relative to CWD, not repo root — path diverges depending on where `chainlit run` is called from.
- **Blast radius**: Local/User-visible. ChromaDB creates a new empty store on each run from a different directory.
- **Mitigation**: Path is anchored via `REPO_ROOT / settings.chroma_persist_directory.lstrip("./")` in `rag.py`.
- **Rollback**: Delete `data/vectorstore/` and re-run — ChromaDB is a cache, not a source of truth.

- **Risk**: Wikipedia `DisambiguationError` for common artist names (e.g. "Genesis" matches band + biblical book).
- **Blast radius**: Local. `_fetch_wikipedia` returns `None`; Tavily fallback activates.
- **Mitigation**: Catch `wikipedia.exceptions.DisambiguationError` in `_fetch_wikipedia`.
- **Rollback**: Fix exception handling — no data affected.

### Step 8: Related artists fetch
- **Risk**: `SpotifyClient.get` call fails if OAuth token is expired — raises `SpotifyClientError`.
- **Blast radius**: User-visible. Tool returns error string.
- **Mitigation**: Tool wraps call in try/except and returns `f"Spotify auth needed: {e}"`.
- **Rollback**: Not applicable (auth failure, not a code bug).

### Step 9: Chainlit wiring
- **Risk**: `graph.ainvoke` blocks the event loop if any tool is synchronous-heavy (e.g. 200ms corpus scan inside an async context).
- **Blast radius**: User-visible. UI freezes during recommendation queries.
- **Mitigation**: Wrap synchronous tool calls with `asyncio.get_event_loop().run_in_executor(None, fn, ...)` or use `make_async` from Chainlit.
- **Rollback**: `git checkout src/app/main.py` restores stub.
- **Verify rollback**: `chainlit run` returns stub responses.

### Global rollback
```bash
git revert HEAD~N..HEAD --no-edit   # where N = number of steps applied
uv run pytest tests/unit/ --tb=short -q   # confirm 190 tests pass
```

---

## Dependency map

```
Step 1  (paths.py + train)
  |
Step 2  (AgentState)
  |
Step 3  (tools.py) ← depends on Step 1 (MODELS_DIR, DATA_DIR)
  |
Step 4  (nodes.py + graph.py) ← depends on Steps 2 + 3
  |
Step 5  (smoke test) ← depends on Steps 1 + 4 (needs trained models + graph)
  |
Step 6  (rag.py) ← independent of Steps 2–5, but best after Step 1 (paths.py)
  |
Step 7  (wire RAG into tools) ← depends on Steps 3 + 6
  |
Step 8  (related artists) ← depends on Step 3 (tools.py exists)
  |
Step 9  (Chainlit) ← depends on Steps 4 + 7 + 8 (full graph with all tools)
```
