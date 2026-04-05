"""Shared memory store for the ENOA agent.

Provides a vector-indexed ``InMemoryStore`` backed by the local
sentence-transformers model (already installed for Track2Vec).

Namespaces:
    ("enoa", user_id, "sessions")   — episodic: past recommendation sessions
    ("enoa", user_id, "taste")      — semantic: user taste facts
    ("enoa", user_id, "strategy")   — procedural: per-user system prompt tweaks
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langgraph.store.memory import InMemoryStore

from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Embedding wrapper — reuses sentence-transformers already in the venv
# ---------------------------------------------------------------------------

# Embedding dimension for all-MiniLM-L6-v2
_EMBEDDING_DIMS = 384


class SentenceTransformerEmbeddings(Embeddings):
    """Thin LangChain-compatible wrapper around sentence-transformers."""

    def __init__(self, model_name: str = settings.embedding_model) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts."""
        return self._model.encode(texts).tolist()

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        return self._model.encode(text).tolist()


# ---------------------------------------------------------------------------
# Store singleton
# ---------------------------------------------------------------------------
_store: InMemoryStore | None = None


def get_store() -> InMemoryStore:
    """Return the singleton ``InMemoryStore`` with vector indexing enabled."""
    global _store  # noqa: PLW0603
    if _store is None:
        embeddings = SentenceTransformerEmbeddings()
        _store = InMemoryStore(
            index={"embed": embeddings, "dims": _EMBEDDING_DIMS},
        )
        log.info("agent.memory_store.init", embedding_model=settings.embedding_model)
    return _store


# ---------------------------------------------------------------------------
# Procedural memory helpers — per-user system prompt strategy
# ---------------------------------------------------------------------------

_PROCEDURAL_KEY = "system_instructions"


async def get_procedural_prompt(user_id: str, store: InMemoryStore) -> str | None:
    """Retrieve the user's custom system prompt instructions, or None."""
    item = await store.aget(("enoa", user_id, "strategy"), _PROCEDURAL_KEY)
    if item is None:
        return None
    return item.value.get("instructions")


async def update_procedural_prompt(
    user_id: str,
    instructions: str,
    store: InMemoryStore,
) -> None:
    """Write or overwrite the user's procedural prompt."""
    await store.aput(
        ("enoa", user_id, "strategy"),
        _PROCEDURAL_KEY,
        {"instructions": instructions},
        index=False,
    )
    log.info("agent.procedural.updated", user_id=user_id)
