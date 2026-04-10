"""Thin production orchestrator for music knowledge RAG.

Wires: MiniLMEmbedder → ChromaRetriever → lazy-fetch → ingest → return.
This is what the agent MCP tools call — no LangGraph overhead.
"""

from __future__ import annotations

from preprocessing.chunker import ChunkerConfig, StructuredChunker
from preprocessing.fetchers import fetch_tavily, fetch_wikipedia
from retrieval.chroma_client import ChromaRetriever
from retrieval.embedder import MiniLMEmbedder

from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

_CHUNK_CONFIG = ChunkerConfig(max_tokens=512, overlap_tokens=64, min_tokens=50)

_NO_CONTENT_MESSAGE = (
    "I couldn't find detailed information about that topic. "
    "Try asking about a well-known artist, band, or music genre."
)


class MusicRAG:
    """Lazy-ingestion RAG for artist/genre knowledge queries.

    Flow:
        1. Normalize subject
        2. Check has_subject (cheap Chroma metadata query)
        3. Cache hit  → embed query → search → return passages
        4. Cache miss → fetch Wikipedia (fallback Tavily) → chunk → embed → upsert → search → return
    """

    def __init__(
        self,
        embedder: MiniLMEmbedder | None = None,
        client: ChromaRetriever | None = None,
    ) -> None:
        self._embedder = embedder or MiniLMEmbedder()
        self._client = client or ChromaRetriever()
        self._chunker = StructuredChunker(_CHUNK_CONFIG)

    def get_context(self, subject: str, top_k: int | None = None) -> str:
        """Return relevant passages for *subject*, ingesting on cache miss.

        Args:
            subject: Artist name, band name, or genre to look up.
            top_k:   Number of passages to return. Defaults to settings.rag_top_k.

        Returns:
            Concatenated passage text, or a fallback message if nothing found.
        """
        if top_k is None:
            top_k = settings.rag_top_k
        normalized = subject.strip().lower()

        if not self._client.has_subject(normalized):
            log.info("music_rag.cache_miss", subject=normalized)
            ingested = self._ingest(subject, normalized)
            if not ingested:
                return _NO_CONTENT_MESSAGE

        query_vector = self._embedder.embed_query(subject)
        results = self._client.search_sync(
            query_text=subject,
            query_vector=query_vector,
            k=top_k,
            subject_filter=normalized,
        )

        if not results:
            return _NO_CONTENT_MESSAGE

        passages = [r.chunk.text for r in results]
        log.info("music_rag.context_ready", subject=normalized, n_passages=len(passages))
        return "\n\n---\n\n".join(passages)

    def _ingest(self, subject: str, normalized: str) -> bool:
        """Fetch, chunk, embed, and upsert content for *subject*.

        Returns True if at least one chunk was ingested.
        """
        content = fetch_wikipedia(subject, language=settings.wikipedia_language)
        if content is None:
            log.info("music_rag.wikipedia_miss", subject=subject)
            content = fetch_tavily(subject)

        if content is None:
            log.info("music_rag.no_content", subject=subject)
            return False

        doc = {
            "url": f"https://en.wikipedia.org/wiki/{subject.replace(' ', '_')}",
            "title": normalized,
            "section": "bio",
            "text": content,
        }
        chunks = self._chunker.chunk_document(doc)
        if not chunks:
            log.warning("music_rag.no_chunks", subject=subject)
            return False

        texts = [c.text for c in chunks]
        embeddings = self._embedder.embed_passages(texts)
        self._client.upsert_chunks(chunks, embeddings)

        log.info("music_rag.ingested", subject=normalized, n_chunks=len(chunks))
        return True
