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
- **AgentState expansion** — `context_docs` field added here only if needed for
  RAG passage injection; otherwise tools return passages as strings via ToolNode

---

## Goal

Add artist-context RAG (Wikipedia + Tavily → ChromaDB) and a related-artists
Spotify tool to the existing ReAct agent. After this phase, the agent can
answer "who is Aphex Twin?" and "who sounds like Radiohead?" with real data.

---

## Steps

### Step 1: `src/agent/rag.py` — Wikipedia + Tavily + ChromaDB

**Files**: `src/agent/rag.py` (new), `tests/unit/agent/test_rag.py` (new),
`.env.example` (add `TAVILY_API_KEY`), `src/utils/config.py` (add `tavily_api_key` if missing)

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

**Snippet**:
```python
# src/agent/rag.py
from __future__ import annotations
import chromadb
from sentence_transformers import SentenceTransformer
from paths import REPO_ROOT
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

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
    results = _collection.query(
        query_embeddings=_embedder.encode([artist_name]).tolist(),
        n_results=top_k,
        where={"artist": artist_name},
    )
    docs = results.get("documents", [[]])[0]
    if docs and any(d.strip() for d in docs):
        return "\n\n".join(docs)

    # 2. cache miss → fetch + ingest
    text = _fetch_wikipedia(artist_name) or _fetch_tavily(artist_name)
    if not text:
        return f"No information found about {artist_name}."
    _ingest(artist_name, text)

    # 3. re-query after ingest
    results = _collection.query(
        query_embeddings=_embedder.encode([artist_name]).tolist(),
        n_results=top_k,
        where={"artist": artist_name},
    )
    docs = results.get("documents", [[]])[0]
    return "\n\n".join(docs) if docs else f"No information found about {artist_name}."


def _fetch_wikipedia(artist_name: str) -> str | None:
    """Return page content or None if not found / too short."""
    import wikipedia
    try:
        search_results = wikipedia.search(artist_name, results=3)
        if not search_results:
            return None
        page = wikipedia.page(search_results[0], auto_suggest=False)
        return page.content
    except wikipedia.exceptions.DisambiguationError as exc:
        # Try first option from disambiguation
        if exc.options:
            try:
                page = wikipedia.page(exc.options[0], auto_suggest=False)
                return page.content
            except Exception:
                return None
        return None
    except Exception:
        return None


def _fetch_tavily(artist_name: str) -> str | None:
    """Fallback: Tavily web search for artist bio."""
    if not settings.tavily_api_key:
        return None
    from tavily import TavilyClient
    client = TavilyClient(api_key=settings.tavily_api_key)
    resp = client.search(
        f"{artist_name} musician biography interesting facts",
        max_results=3,
    )
    return "\n\n".join(r["content"] for r in resp.get("results", []))


def _chunk_text(text: str) -> list[str]:
    """Split text into overlapping character-based chunks (~400 tokens)."""
    size = _CHUNK_SIZE * 4   # chars
    step = (_CHUNK_SIZE - _CHUNK_OVERLAP) * 4
    return [
        text[i : i + size]
        for i in range(0, len(text), step)
        if text[i : i + size].strip()
    ]


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
    log.info("rag.ingest", artist=artist_name, n_chunks=len(chunks))
```

**Tests** (mock Wikipedia and Tavily — no network in unit tests):
```python
# tests/unit/agent/test_rag.py
from unittest.mock import patch, MagicMock

def test_get_artist_context_wikipedia_hit(tmp_path, monkeypatch):
    """Cache miss → Wikipedia fetch → returns passages."""
    with patch("agent.rag._fetch_wikipedia", return_value="Aphex Twin is ...") as mock_wiki, \
         patch("agent.rag._collection") as mock_col:
        mock_col.query.side_effect = [
            {"documents": [[]]},      # first query: cache miss
            {"documents": [["Aphex Twin is ..."]]},  # after ingest
        ]
        mock_col.upsert = MagicMock()
        from agent.rag import get_artist_context
        result = get_artist_context("Aphex Twin", top_k=2)
    mock_wiki.assert_called_once_with("Aphex Twin")
    assert isinstance(result, str)
    assert len(result) > 0

def test_get_artist_context_tavily_fallback():
    """Wikipedia miss → Tavily fallback."""
    with patch("agent.rag._fetch_wikipedia", return_value=None), \
         patch("agent.rag._fetch_tavily", return_value="Facts about artist") as mock_tav, \
         patch("agent.rag._collection") as mock_col:
        mock_col.query.side_effect = [
            {"documents": [[]]},
            {"documents": [["Facts about artist"]]},
        ]
        mock_col.upsert = MagicMock()
        from agent.rag import get_artist_context
        result = get_artist_context("Niche Artist", top_k=2)
    mock_tav.assert_called_once()
    assert "Facts" in result

def test_chunk_text_creates_overlapping_chunks():
    from agent.rag import _chunk_text
    text = "a" * 2000
    chunks = _chunk_text(text)
    assert len(chunks) > 1

def test_get_artist_context_cache_hit():
    """Cache hit → no fetch needed."""
    with patch("agent.rag._fetch_wikipedia") as mock_wiki, \
         patch("agent.rag._collection") as mock_col:
        mock_col.query.return_value = {"documents": [["Cached bio passage"]]}
        from agent.rag import get_artist_context
        result = get_artist_context("Cached Artist")
    mock_wiki.assert_not_called()  # no fetch
    assert "Cached bio passage" in result
```

**Run**: `uv run pytest tests/unit/agent/test_rag.py -v`

**Done when**: Unit tests pass; `get_artist_context("Aphex Twin")` returns
non-empty string in a REPL (requires internet).

---

### Step 2: Wire RAG tool into agent

**Files**: `src/agent/tools.py` (add tool + update `ALL_TOOLS`),
`src/agent/nodes.py` (update system prompt)

**What**: Add `get_artist_context` as a `StructuredTool`. Append to `ALL_TOOLS`.
The ReAct graph picks it up automatically via ToolNode. Update system prompt to
mention the new tool.

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

ALL_TOOLS.append(get_artist_context_tool)
```

**System prompt addition** (`nodes.py`):
```
- Use get_artist_context for "who is X?", "tell me about X", artist trivia
```

**Test**:
```python
def test_artist_context_tool_in_all_tools():
    from agent.tools import ALL_TOOLS
    names = [t.name for t in ALL_TOOLS]
    assert "get_artist_context" in names
```

**Run**: `uv run pytest tests/unit/agent/ -v`

**Done when**: `ALL_TOOLS` contains 7 tools; smoke test with "who is Aphex Twin?"
routes to `get_artist_context`.

---

### Step 3: Related artists tool — new Spotify fetch + agent tool

**Files**: `src/spotify/fetch.py` (add `fetch_related_artists`),
`src/agent/tools.py` (add tool + update `ALL_TOOLS`),
`tests/unit/agent/test_tools.py` (extend),
`tests/unit/test_spotify_client.py` (extend)

**What**: Add `fetch_related_artists(client, artist_id)` to `fetch.py`.
Wrap as `StructuredTool` in `tools.py`. Fills the "who sounds like X?" gap.

**Snippet**:
```python
# src/spotify/fetch.py — add:
def fetch_related_artists(client: SpotifyClient, artist_id: str) -> list[dict]:
    """Fetch up to 20 related artists for a given artist ID."""
    response = client.get(f"artists/{artist_id}/related-artists")
    artists = response.get("artists", [])
    log.info("spotify.fetch_related_artists", artist_id=artist_id, n=len(artists))
    return [
        {"id": a["id"], "name": a["name"], "genres": a.get("genres", [])}
        for a in artists
    ]

# src/agent/tools.py — add:
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

get_related_artists_tool = StructuredTool.from_function(
    _get_related_artists,
    name="get_related_artists",
    description="Find artists that sound similar to a Spotify artist ID. Use for 'who sounds like X?' queries.",
)

ALL_TOOLS.append(get_related_artists_tool)
```

**Tests**:
```python
# tests/unit/test_spotify_client.py — add:
def test_fetch_related_artists_empty():
    mock_client = MagicMock()
    mock_client.get.return_value = {"artists": []}
    result = fetch_related_artists(mock_client, "some_id")
    assert result == []

# tests/unit/agent/test_tools.py — add:
def test_get_related_artists_formats_output():
    # Mock _get_client + fetch_related_artists → list of dicts
    # Assert formatted string with artist names
```

**Run**: `uv run pytest tests/unit/agent/test_tools.py tests/unit/test_spotify_client.py -v`

**Done when**: `ALL_TOOLS` contains 8 tools; `fetch_related_artists` tested.

---

### Step 4: End-to-end validation

**Files**: None. Manual validation.

**Smoke tests** (in Chainlit via `make app`):
1. `"who is Aphex Twin?"` → get_artist_context → Wikipedia passages
2. `"who sounds like Radiohead?"` → search_tracks (find artist ID) →
   get_related_artists → list of similar artists
3. `"recommend zouk tracks"` → recommend_by_genre → numbered list (Phase 3c still works)

**Cost note**: 2-4 Anthropic API calls + potential Wikipedia/Tavily fetches.
Confirm before running.

**Done when**: All three query types produce useful responses in Chainlit.

---

## Test Plan

| Step | Test command | Verifies |
|------|-------------|----------|
| 1 | `uv run pytest tests/unit/agent/test_rag.py -v` | RAG fetch/chunk/ingest (mocked) |
| 2 | `uv run pytest tests/unit/agent/ -v` | RAG tool wired; all agent tests pass |
| 3 | `uv run pytest tests/unit/agent/test_tools.py tests/unit/test_spotify_client.py -v` | Related artists fetch + tool |
| 4 | `make app` + manual | Full end-to-end in Chainlit |

**Full regression**: `uv run pytest tests/unit/ --tb=short -q`

---

## Risks & Rollback

### Step 1: ChromaDB path diverges by CWD
- **Mitigation**: Path anchored via `REPO_ROOT / settings.chroma_persist_directory`
- **Rollback**: Delete `data/vectorstore/` — ChromaDB is a cache, not source of truth

### Step 1: Wikipedia DisambiguationError
- **Mitigation**: Catch explicitly, try first disambiguation option, fall back to Tavily
- **Rollback**: Fix exception handling — no data affected

### Step 3: Spotify auth expired
- **Mitigation**: Tool wraps call in try/except, returns `f"Failed to fetch: {exc}"`
- **Rollback**: Not a code bug — re-auth via `make auth`

### Global rollback
```bash
git revert HEAD~N..HEAD --no-edit
uv run pytest tests/unit/ --tb=short -q
```

---

## Dependency map

```
Step 1 (rag.py) ← independent; needs chromadb + sentence-transformers (installed)
  ↓
Step 2 (wire RAG tool) ← needs Step 1 + Phase 3c tools.py
  ↓
Step 3 (related artists) ← needs Phase 3c tools.py (independent of Step 1-2)
  ↓
Step 4 (validation) ← needs Steps 1-3
```

---

> **Phase 4a ends here. Phase 4b (long-term memory) follows — see `phase4_memory.md`.**
