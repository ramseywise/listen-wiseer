"""Shared memory store for the ENOA agent.

When MEMORY_STORE_URL is set, uses AsyncPostgresStore for persistence across restarts.
Otherwise falls back to InMemoryStore (dev / single-session use), vector-indexed by the
local sentence-transformers model when the optional ``embeddings`` extra is installed
(``uv sync --extra embeddings``). Without it the store is unindexed: ``asearch(query=...)``
still filters by namespace but returns items unranked.

Namespaces:
    ("enoa", user_id, "sessions")   — episodic: past recommendation sessions
    ("enoa", user_id, "taste")      — semantic: user taste facts
    ("enoa", user_id, "strategy")   — procedural: per-user system prompt tweaks
"""

from __future__ import annotations

from contextlib import AsyncExitStack

from langchain_core.embeddings import Embeddings
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.store.postgres import AsyncPostgresStore

from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Embedding wrapper — sentence-transformers is an optional extra (`embeddings`)
# ---------------------------------------------------------------------------

# Embedding dimension for all-MiniLM-L6-v2
_EMBEDDING_DIMS = 384


class SentenceTransformerEmbeddings(Embeddings):
    """Thin LangChain-compatible wrapper around sentence-transformers."""

    def __init__(self, model_name: str = settings.embedding_model) -> None:
        # Optional extra (`embeddings`); ImportError is handled by _load_embeddings().
        from sentence_transformers import SentenceTransformer  # pyright: ignore[reportMissingImports]

        self._model = SentenceTransformer(model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts."""
        return self._model.encode(texts).tolist()

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        return self._model.encode(text).tolist()


def _load_embeddings() -> Embeddings | None:
    """Return the sentence-transformers embedder, or None if the extra is not installed."""
    try:
        return SentenceTransformerEmbeddings()
    except ImportError as exc:
        log.warning(
            "agent.memory_store.embeddings_unavailable",
            reason=str(exc),
            hint="uv sync --extra embeddings for semantic memory search",
        )
        return None


# ---------------------------------------------------------------------------
# Store singleton — async to support Postgres context manager lifecycle
# ---------------------------------------------------------------------------
_store: BaseStore | None = None
_store_exit_stack: AsyncExitStack | None = None


async def get_store() -> BaseStore:
    """Return the singleton store, creating it on first call.

    Priority: MEMORY_STORE_URL (Postgres) > InMemoryStore (dev).
    """
    global _store, _store_exit_stack  # noqa: PLW0603
    if _store is not None:
        return _store

    if settings.memory_store_url:
        stack = AsyncExitStack()
        store = await stack.enter_async_context(
            AsyncPostgresStore.from_conn_string(settings.memory_store_url)
        )
        await store.setup()
        _store_exit_stack = stack
        _store = store
        log.info("agent.memory_store.postgres")
    else:
        embeddings = _load_embeddings()
        if embeddings is None:
            _store = InMemoryStore()
            log.info("agent.memory_store.init", embedding_model=None)
        else:
            _store = InMemoryStore(
                index={"embed": embeddings, "dims": _EMBEDDING_DIMS},
            )
            log.info("agent.memory_store.init", embedding_model=settings.embedding_model)

    return _store


async def shutdown_store() -> None:
    """Clean up the store connection on app shutdown."""
    global _store, _store_exit_stack  # noqa: PLW0603
    if _store_exit_stack is not None:
        await _store_exit_stack.aclose()
        _store_exit_stack = None
    _store = None
    log.info("agent.memory_store.closed")


# ---------------------------------------------------------------------------
# Procedural memory helpers — per-user system prompt strategy
# ---------------------------------------------------------------------------

_PROCEDURAL_KEY = "system_instructions"


async def get_procedural_prompt(user_id: str, store: BaseStore) -> str | None:
    """Retrieve the user's custom system prompt instructions, or None."""
    item = await store.aget(("enoa", user_id, "strategy"), _PROCEDURAL_KEY)
    if item is None:
        return None
    return item.value.get("instructions")


async def update_procedural_prompt(
    user_id: str,
    instructions: str,
    store: BaseStore,
) -> None:
    """Write or overwrite the user's procedural prompt."""
    await store.aput(
        ("enoa", user_id, "strategy"),
        _PROCEDURAL_KEY,
        {"instructions": instructions},
        index=False,
    )
    log.info("agent.procedural.updated", user_id=user_id)
