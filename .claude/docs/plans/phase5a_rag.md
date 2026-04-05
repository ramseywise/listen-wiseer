# Plan: Phase 5a — RAG Core Adaptation
Date: 2026-04-05
Predecessor: Phase 4b (memory) — DONE
Next: Phase 5b (intent routing + query understanding)

---

## Context & What Exists

`rag_core/` was built for a **Danish customer support assistant** using OpenSearch.
Key differences from listen-wiseer:

| Aspect | Current (help-assistant) | Target (listen-wiseer) |
|--------|--------------------------|------------------------|
| Vector store | OpenSearch (async, knn_vector) | ChromaDB (PersistentClient, local) |
| Embedder | `multilingual-e5-large` (1024-dim, E5 prefix) | `all-MiniLM-L6-v2` (384-dim, already in settings) |
| Data source | Scraped HTML docs | Wikipedia + Tavily (on-demand fetch) |
| Language | Danish prompts + intents | English |
| Intent enum | HOW_TO / TROUBLESHOOT / REFERENCE / CHIT_CHAT / OUT_OF_SCOPE | ARTIST_INFO / GENRE_INFO / HISTORY / CHIT_CHAT / OUT_OF_SCOPE |
| Reranker | Stub (NotImplementedError) | Stub OK for now |

**Goal**: Adapt `rag_core/` for listen-wiseer — swap retrieval backend to ChromaDB,
adapt embedder, add music intents, rewrite prompts in English for music context,
and expose a single `artist_context_tool` to the agent. Keep the Registry pattern
and modular chunker strategies — these are correct and reusable.

**Production principle**: The agent tool calls a thin orchestrator
(`src/rag_core/orchestration/music_rag.py`) that wires the modules directly —
no full LangGraph sub-graph overhead for a single tool call.
The existing `graph.py` pipeline is useful for notebooks and eval harness, not production.

---

## Out of Scope

- Spotify `/recommendations` API — Phase 6
- Long-term memory changes — Phase 4b (done)
- Eval harness — Phase 5c
- Reranker implementation (Cohere / cross-encoder) — deferred, stub is fine

---

## Steps

### Step 1: Swap retrieval backend — ChromaDB client

**Files**:
- `src/rag_core/retrieval/chroma_client.py` (new)
- `src/rag_core/registry.py` (add ChromaDB registration)
- `src/utils/config.py` (verify `chroma_persist_directory` + `embedding_model` exist)
- `tests/unit/rag/test_chroma_client.py` (new)

**What**: Implement `ChromaClient` mirroring `OpenSearchClient`'s interface
(`upsert_chunks`, `search`) so it can drop in via the Registry.
Uses `all-MiniLM-L6-v2` (384 dims). Anchored via `REPO_ROOT`.

**Snippet**:
```python
# src/rag_core/retrieval/chroma_client.py
from __future__ import annotations

import chromadb
from schemas.chunks import Chunk, ChunkMetadata
from schemas.retrieval import RetrievalResult
from paths import REPO_ROOT
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

_DIMS = 384  # all-MiniLM-L6-v2


class ChromaClient:
    """ChromaDB retrieval backend — drop-in replacement for OpenSearchClient.

    Uses cosine similarity. Collection is created on first use.
    """

    def __init__(self, collection_name: str = "artist_info") -> None:
        db_path = str(REPO_ROOT / settings.chroma_persist_directory.lstrip("./"))
        self._client = chromadb.PersistentClient(path=db_path)
        self._col = self._client.get_or_create_collection(
            collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        log.info("chroma.init", collection=collection_name, path=db_path)

    def search(
        self,
        query_vector: list[float],
        k: int = 5,
        where: dict | None = None,
    ) -> list[RetrievalResult]:
        """Query ChromaDB and return ranked RetrievalResults."""
        kwargs: dict = {"query_embeddings": [query_vector], "n_results=k"}
        if where:
            kwargs["where"] = where
        results = self._col.query(**kwargs)
        docs = results.get("documents", [[]])[0]
        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metas = results.get("metadatas", [[]])[0]

        out: list[RetrievalResult] = []
        for doc, cid, dist, meta in zip(docs, ids, distances, metas):
            chunk = Chunk(
                id=cid,
                text=doc,
                metadata=ChunkMetadata(
                    url=meta.get("source", ""),
                    title=meta.get("artist", ""),
                    section=meta.get("section", ""),
                    doc_id=cid,
                ),
            )
            # ChromaDB cosine distance → similarity score (1 - distance)
            out.append(RetrievalResult(chunk=chunk, score=1.0 - dist, source="vector"))
        log.info("chroma.search.done", n_results=len(out))
        return out

    def upsert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Bulk upsert chunks with precomputed embeddings."""
        if not chunks:
            return
        self._col.upsert(
            ids=[c.id for c in chunks],
            embeddings=embeddings,
            documents=[c.text for c in chunks],
            metadatas=[
                {
                    "artist": c.metadata.title,
                    "section": c.metadata.section,
                    "source": c.metadata.url,
                }
                for c in chunks
            ],
        )
        log.info("chroma.upsert.done", n_chunks=len(chunks))
```

**Registry addition** (`registry.py`):
```python
from retrieval.chroma_client import ChromaClient
Registry.register("client", "chroma")(ChromaClient)
```

**Config check** — `src/utils/config.py` must have:
```python
chroma_persist_directory: str = "./data/vectorstore"
embedding_model: str = "all-MiniLM-L6-v2"
```
Add if missing.

**Tests**:
```python
# tests/unit/rag/test_chroma_client.py
def test_chroma_upsert_and_search(tmp_path, monkeypatch):
    monkeypatch.setattr("rag_core.retrieval.chroma_client.REPO_ROOT", tmp_path)
    from rag_core.retrieval.chroma_client import ChromaClient
    from rag_core.schemas.chunks import Chunk, ChunkMetadata
    client = ChromaClient(collection_name="test")
    chunk = Chunk(id="c1", text="Aphex Twin is an electronic music producer.",
                  metadata=ChunkMetadata(url="", title="Aphex Twin", section="bio", doc_id="c1"))
    embedding = [0.1] * 384
    client.upsert_chunks([chunk], [embedding])
    results = client.search(query_vector=embedding, k=1)
    assert len(results) == 1
    assert results[0].chunk.id == "c1"
```

**Run**: `uv run pytest tests/unit/rag/test_chroma_client.py -v`

**Done when**: upsert + search round-trip passes; `Registry.list_modules()` shows `"chroma"`.

---

### Step 2: Adapt embedder — swap to `all-MiniLM-L6-v2`

**Files**:
- `src/rag_core/retrieval/embedder.py` (add `MiniLMEmbedder`, keep `MultilingualEmbedder`)
- `src/rag_core/registry.py` (register `MiniLMEmbedder`)
- `tests/unit/rag/test_embedder.py` (new)

**What**: Add `MiniLMEmbedder` wrapping `all-MiniLM-L6-v2` (384-dim, no prefix required).
Keep `MultilingualEmbedder` for backwards compatibility.
`MiniLMEmbedder` is the default for listen-wiseer.

**Snippet**:
```python
# src/rag_core/retrieval/embedder.py — add:
class MiniLMEmbedder:
    """Wraps all-MiniLM-L6-v2 (384 dims). No prefix required."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model = SentenceTransformer(model_name)

    def embed_query(self, text: str) -> list[float]:
        return self.model.encode(text, convert_to_numpy=True).tolist()

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, convert_to_numpy=True).tolist()
```

**Registry**:
```python
Registry.register("embedder", "minilm")(MiniLMEmbedder)
Registry.register("embedder", "multilingual")(MultilingualEmbedder)
```

**Tests**:
```python
def test_minilm_embed_query_shape():
    from rag_core.retrieval.embedder import MiniLMEmbedder
    embedder = MiniLMEmbedder()
    vec = embedder.embed_query("Aphex Twin electronic music")
    assert len(vec) == 384
    assert all(isinstance(v, float) for v in vec)

def test_minilm_embed_passages_batch():
    from rag_core.retrieval.embedder import MiniLMEmbedder
    embedder = MiniLMEmbedder()
    vecs = embedder.embed_passages(["text one", "text two"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 384
```

**Run**: `uv run pytest tests/unit/rag/test_embedder.py -v`

**Done when**: `MiniLMEmbedder` returns 384-dim vectors; registered in Registry.

---

### Step 3: Adapt schemas — music intents + ChunkMetadata source field

**Files**:
- `src/rag_core/schemas/retrieval.py` (extend `Intent`, add `source` to `RetrievalResult`)
- `src/rag_core/schemas/chunks.py` (verify `ChunkMetadata` has `source` or use `url`)
- `tests/unit/rag/test_schemas.py` (new)

**What**: Replace generic intents with music-specific ones.
Keep `CHIT_CHAT` and `OUT_OF_SCOPE` — they're universal.

```python
# src/rag_core/schemas/retrieval.py
class Intent(StrEnum):
    ARTIST_INFO = "artist_info"    # "who is Aphex Twin?", "tell me about Radiohead"
    GENRE_INFO = "genre_info"      # "what is zouk?", "explain bossa nova"
    HISTORY = "history"            # "what have I been listening to?", "my recent plays"
    CHIT_CHAT = "chit_chat"        # greetings, small talk
    OUT_OF_SCOPE = "out_of_scope"  # unrelated to music
```

**Tests**:
```python
def test_intent_values():
    from rag_core.schemas.retrieval import Intent
    assert Intent.ARTIST_INFO == "artist_info"
    assert Intent.GENRE_INFO == "genre_info"
    assert Intent.HISTORY == "history"
```

**Run**: `uv run pytest tests/unit/rag/test_schemas.py -v`

**Done when**: `Intent` has music values; existing graph tests updated to use new enum.

---

### Step 4: Data fetchers — Wikipedia + Tavily

**Files**:
- `src/rag_core/preprocessing/fetchers.py` (new)
- `tests/unit/rag/test_fetchers.py` (new)

**What**: Implement `fetch_wikipedia` and `fetch_tavily` — on-demand content
fetchers for the lazy-ingestion pipeline. These are pure functions, not classes.

```python
# src/rag_core/preprocessing/fetchers.py
from __future__ import annotations

import wikipedia
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)


def fetch_wikipedia(subject: str) -> str | None:
    """Fetch Wikipedia content for subject. Returns None on failure."""
    try:
        results = wikipedia.search(subject, results=3)
        if not results:
            return None
        page = wikipedia.page(results[0], auto_suggest=False)
        log.info("rag.fetch.wikipedia", subject=subject, title=page.title)
        return page.content
    except wikipedia.exceptions.DisambiguationError as exc:
        if exc.options:
            try:
                page = wikipedia.page(exc.options[0], auto_suggest=False)
                return page.content
            except Exception:
                return None
        return None
    except Exception as exc:
        log.warning("rag.fetch.wikipedia.failed", subject=subject, error=str(exc))
        return None


def fetch_tavily(subject: str, context: str = "musician biography") -> str | None:
    """Tavily web search fallback. Returns None if no API key or on failure."""
    if not settings.tavily_api_key:
        return None
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        resp = client.search(f"{subject} {context}", max_results=3)
        texts = [r["content"] for r in resp.get("results", []) if r.get("content")]
        if not texts:
            return None
        log.info("rag.fetch.tavily", subject=subject, n_results=len(texts))
        return "\n\n".join(texts)
    except Exception as exc:
        log.warning("rag.fetch.tavily.failed", subject=subject, error=str(exc))
        return None
```

**Config**: add to `src/utils/config.py`:
```python
tavily_api_key: str = ""
```
Add `TAVILY_API_KEY=` to `.env.example`.

**Tests** (mock network — no real calls):
```python
def test_fetch_wikipedia_returns_content(monkeypatch):
    import wikipedia as wp
    monkeypatch.setattr(wp, "search", lambda *a, **kw: ["Aphex Twin"])
    mock_page = MagicMock(); mock_page.content = "Aphex Twin is..."
    monkeypatch.setattr(wp, "page", lambda *a, **kw: mock_page)
    from rag_core.preprocessing.fetchers import fetch_wikipedia
    assert "Aphex Twin" in fetch_wikipedia("Aphex Twin")

def test_fetch_wikipedia_disambiguation(monkeypatch):
    import wikipedia as wp
    exc = wp.exceptions.DisambiguationError("Genesis", ["Genesis (band)", "Genesis (book)"])
    monkeypatch.setattr(wp, "search", lambda *a, **kw: ["Genesis"])
    monkeypatch.setattr(wp, "page", MagicMock(side_effect=[exc, MagicMock(content="Genesis band...")]))
    from rag_core.preprocessing.fetchers import fetch_wikipedia
    result = fetch_wikipedia("Genesis")
    assert result is not None

def test_fetch_tavily_no_key(monkeypatch):
    monkeypatch.setattr("rag_core.preprocessing.fetchers.settings", MagicMock(tavily_api_key=""))
    from rag_core.preprocessing.fetchers import fetch_tavily
    assert fetch_tavily("Aphex Twin") is None
```

**Run**: `uv run pytest tests/unit/rag/test_fetchers.py -v`

**Done when**: Both fetchers importable and tested with mocks.

---

### Step 5: Music RAG orchestrator — production script

**Files**:
- `src/rag_core/orchestration/music_rag.py` (new)
- `tests/unit/rag/test_music_rag.py` (new)

**What**: Thin production orchestrator — no LangGraph overhead.
Wires: `MiniLMEmbedder` → `ChromaClient` → lazy-fetch → ingest → return passages.
This is what the agent tool calls.

```python
# src/rag_core/orchestration/music_rag.py
from __future__ import annotations

from rag_core.preprocessing.chunker import StructuredChunker, ChunkerConfig
from rag_core.preprocessing.fetchers import fetch_wikipedia, fetch_tavily
from rag_core.retrieval.chroma_client import ChromaClient
from rag_core.retrieval.embedder import MiniLMEmbedder
from utils.logging import get_logger

log = get_logger(__name__)

_CHUNK_CONFIG = ChunkerConfig(max_tokens=400, overlap_tokens=50, min_tokens=30)
_CACHE_MISS_THRESHOLD = 0  # re-fetch if 0 chunks found for this artist


class MusicRAG:
    """Production RAG orchestrator for listen-wiseer.

    Lazy ingestion: on first query for an artist, fetches Wikipedia (or Tavily
    fallback), chunks, embeds, and upserts to ChromaDB. Subsequent queries hit cache.

    Usage:
        rag = MusicRAG()
        passages = rag.get_context("Aphex Twin", top_k=3)
    """

    def __init__(self) -> None:
        self._embedder = MiniLMEmbedder()
        self._client = ChromaClient(collection_name="artist_info")
        self._chunker = StructuredChunker(_CHUNK_CONFIG)

    def get_context(self, subject: str, top_k: int = 3) -> str:
        """Return top_k relevant passages for subject. Fetches and ingests if not cached."""
        query_vec = self._embedder.embed_query(subject)

        # 1. Try cache
        results = self._client.search(
            query_vector=query_vec,
            k=top_k,
            where={"artist": subject},
        )
        if len(results) > _CACHE_MISS_THRESHOLD:
            log.info("rag.cache_hit", subject=subject, n=len(results))
            return "\n\n".join(r.chunk.text for r in results)

        # 2. Cache miss — fetch
        text = fetch_wikipedia(subject) or fetch_tavily(subject)
        if not text:
            log.warning("rag.no_content", subject=subject)
            return f"No information found about {subject}."

        # 3. Chunk + embed + ingest
        doc = {"text": text, "url": f"wikipedia:{subject}", "title": subject, "section": "bio"}
        chunks = self._chunker.chunk_document(doc)
        if not chunks:
            return f"No information found about {subject}."

        # Override metadata so artist filter works
        for chunk in chunks:
            chunk.metadata.title = subject

        embeddings = self._embedder.embed_passages([c.text for c in chunks])
        self._client.upsert_chunks(chunks, embeddings)
        log.info("rag.ingest", subject=subject, n_chunks=len(chunks))

        # 4. Re-query after ingest
        results = self._client.search(query_vector=query_vec, k=top_k, where={"artist": subject})
        if not results:
            return f"No information found about {subject}."
        return "\n\n".join(r.chunk.text for r in results)
```

**Tests**:
```python
# tests/unit/rag/test_music_rag.py
def test_get_context_cache_miss_fetches_wikipedia(tmp_path, monkeypatch):
    """Cache miss → Wikipedia fetch → ingest → returns passages."""
    monkeypatch.setattr("rag_core.retrieval.chroma_client.REPO_ROOT", tmp_path)
    with patch("rag_core.orchestration.music_rag.fetch_wikipedia", return_value="Aphex Twin is...") as mock_wiki, \
         patch("rag_core.orchestration.music_rag.fetch_tavily", return_value=None):
        from rag_core.orchestration.music_rag import MusicRAG
        rag = MusicRAG()
        result = rag.get_context("Aphex Twin", top_k=2)
    mock_wiki.assert_called_once_with("Aphex Twin")
    assert isinstance(result, str)
    assert len(result) > 0

def test_get_context_no_content_returns_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("rag_core.retrieval.chroma_client.REPO_ROOT", tmp_path)
    with patch("rag_core.orchestration.music_rag.fetch_wikipedia", return_value=None), \
         patch("rag_core.orchestration.music_rag.fetch_tavily", return_value=None):
        from rag_core.orchestration.music_rag import MusicRAG
        rag = MusicRAG()
        result = rag.get_context("UnknownArtist999")
    assert "No information found" in result
```

**Run**: `uv run pytest tests/unit/rag/test_music_rag.py -v`

**Done when**: Both tests pass; `MusicRAG().get_context("Aphex Twin")` returns content in REPL (requires internet).

---

### Step 6: Wire `MusicRAG` into agent as tool

**Files**:
- `src/agent/tools.py` (add `get_artist_context_tool`, update `ALL_TOOLS`)
- `src/agent/nodes.py` (update system prompt to mention new tool)
- `tests/unit/agent/test_tools.py` (extend)

**What**: Expose `MusicRAG.get_context` as a `StructuredTool`. Agent calls it
for "who is X?" and "tell me about X" queries. `MusicRAG` is instantiated once
at module load (lazy — no network call at import time).

```python
# src/agent/tools.py — add:
from rag_core.orchestration.music_rag import MusicRAG as _MusicRAG

_music_rag: _MusicRAG | None = None

def _get_music_rag() -> _MusicRAG:
    global _music_rag
    if _music_rag is None:
        _music_rag = _MusicRAG()
    return _music_rag


def _get_artist_context(artist_name: str, top_k: int = 3) -> str:
    """Retrieve artist info from Wikipedia/ChromaDB cache."""
    return _get_music_rag().get_context(artist_name, top_k=top_k)


get_artist_context_tool = StructuredTool.from_function(
    _get_artist_context,
    name="get_artist_context",
    description=(
        "Retrieve biographical info and interesting facts about a musician or band. "
        "Use when the user asks who an artist is, what they're known for, "
        "their history, influences, or style."
    ),
)

ALL_TOOLS.append(get_artist_context_tool)  # now 9 tools
```

**System prompt line** (`nodes.py`):
```
- get_artist_context: use for "who is X?", "tell me about X", artist trivia, history, influences
```

**Tests**:
```python
def test_get_artist_context_tool_in_all_tools():
    from agent.tools import ALL_TOOLS
    assert "get_artist_context" in [t.name for t in ALL_TOOLS]

def test_get_artist_context_tool_callable(monkeypatch):
    with patch("agent.tools._get_music_rag") as mock_rag:
        mock_rag.return_value.get_context.return_value = "Aphex Twin is a pioneer..."
        from agent.tools import get_artist_context_tool
        result = get_artist_context_tool.invoke({"artist_name": "Aphex Twin"})
    assert "Aphex Twin" in result
```

**Run**: `uv run pytest tests/unit/agent/ -v`

**Done when**: `ALL_TOOLS` has 9 tools; smoke: "who is Aphex Twin?" routes to `get_artist_context`.

---

### Step 7: English prompts + music system prompts

**Files**:
- `src/rag_core/generation/generator.py` (replace Danish prompts with English music prompts)
- `tests/unit/rag/test_generator.py` (update)

**What**: Replace Danish `SYSTEM_PROMPTS` with English music-context prompts
keyed to new `Intent` enum. Used by the eval harness notebook (not production graph).

```python
SYSTEM_PROMPTS: dict[Intent, str] = {
    Intent.ARTIST_INFO: (
        "You are a knowledgeable music assistant. "
        "Answer questions about musicians, bands, and artists using the provided context. "
        "Be specific, factual, and engaging."
    ),
    Intent.GENRE_INFO: (
        "You are a music genre expert. "
        "Explain musical genres, their origins, characteristics, and key artists "
        "using the provided context."
    ),
    Intent.HISTORY: (
        "You are a music history assistant. "
        "Help the user understand their listening patterns and music history."
    ),
    Intent.CHIT_CHAT: "You are a friendly music assistant. Respond briefly and warmly.",
    Intent.OUT_OF_SCOPE: (
        "You are a music assistant. Politely explain that the question is outside "
        "your area of expertise (music and artist information)."
    ),
}
```

**Done when**: No Danish strings in `generator.py`; tests pass.

---

### Step 8: End-to-end smoke + regression

**Manual smoke** (run `make app`):
1. `"who is Aphex Twin?"` → `get_artist_context` → Wikipedia passages
2. `"what is zouk music?"` → `get_artist_context` with "zouk" → genre info
3. `"recommend zouk tracks"` → `recommend_by_genre` → still works (regression)

**Regression**:
```bash
uv run pytest tests/unit/ --tb=short -q
```

**Done when**: All 3 smoke queries return useful responses; test count ≥ 280 (pre-phase baseline).

---

## Test Plan

| Step | Command | Verifies |
|------|---------|----------|
| 1 | `uv run pytest tests/unit/rag/test_chroma_client.py -v` | ChromaDB upsert + search |
| 2 | `uv run pytest tests/unit/rag/test_embedder.py -v` | MiniLM 384-dim vectors |
| 3 | `uv run pytest tests/unit/rag/test_schemas.py -v` | Music Intent enum |
| 4 | `uv run pytest tests/unit/rag/test_fetchers.py -v` | Wikipedia + Tavily (mocked) |
| 5 | `uv run pytest tests/unit/rag/test_music_rag.py -v` | Full orchestrator (mocked) |
| 6 | `uv run pytest tests/unit/agent/ -v` | Tool wiring + ALL_TOOLS count |
| 7 | `uv run pytest tests/unit/rag/ -v` | Full RAG test suite |
| 8 | `uv run pytest tests/unit/ --tb=short -q` | Full regression |

---

## Dependency Map

```
Step 1 (ChromaClient) ← independent
Step 2 (MiniLMEmbedder) ← independent
Step 3 (schemas) ← independent; Step 7 depends on it
Step 4 (fetchers) ← needs Step 3
Step 5 (MusicRAG) ← needs Steps 1 + 2 + 4
Step 6 (agent tool) ← needs Step 5
Step 7 (prompts) ← needs Step 3
Step 8 (smoke) ← needs Steps 5 + 6
```

---

## Risks & Rollback

### ChromaDB path (Step 1)
- **Risk**: PersistentClient creates at wrong path if `REPO_ROOT` resolution fails
- **Mitigation**: Anchored via `REPO_ROOT / settings.chroma_persist_directory.lstrip("./")`
- **Rollback**: Delete `data/vectorstore/` — it's a cache, not source of truth

### Model download (Step 2)
- **Risk**: `all-MiniLM-L6-v2` not cached locally → slow first import
- **Mitigation**: Already used by `recommend/` pipeline — should be in HuggingFace cache
- **Rollback**: Not applicable (download, not a code bug)

### Import-time MusicRAG (Step 6)
- **Risk**: `_music_rag` instantiation at first call loads SentenceTransformer → slow
- **Mitigation**: Lazy singleton (`_music_rag is None` guard); not loaded at import
- **Rollback**: `git revert HEAD --no-edit` on `tools.py`

### Wikipedia DisambiguationError (Step 4)
- **Risk**: "Genesis", "Prince", "The Weeknd" → disambiguation page
- **Mitigation**: Catch `DisambiguationError`, try first option, fall back to Tavily
- **Rollback**: Fix exception handling — no data affected

### Global rollback
```bash
git revert HEAD~N..HEAD --no-edit
uv run pytest tests/unit/ --tb=short -q
```
