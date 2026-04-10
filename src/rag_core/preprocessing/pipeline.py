"""Ingestion pipeline: raw text → vector store + MetadataDB + SnippetDB.

Flow for each document:
  1. SHA-256 checksum → skip if already ingested (idempotent re-runs)
  2. Chunk via chunker
  3. Embed passages
  4. Upsert chunks to ChromaRetriever (batched)
  5. Extract sentence-level snippets from raw text
  6. Write snippets to SnippetDB
  7. Write doc metadata to MetadataDB
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from utils.logging import get_logger

if TYPE_CHECKING:
    from retrieval.chroma_client import ChromaRetriever
    from retrieval.embedder import MiniLMEmbedder
    from storage.metadata_db import MetadataDB
    from storage.snippet_db import SnippetDB

    from preprocessing.chunker import StructuredChunker

log = get_logger(__name__)

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_MIN_SNIPPET_LEN = 30
_MAX_SNIPPET_LEN = 400


@dataclass
class IngestionResult:
    """Summary of a single document ingestion run."""

    doc_id: str
    chunk_count: int
    snippet_count: int
    skipped: bool = field(default=False)


class IngestionPipeline:
    """Orchestrates raw-text → ChromaDB + MetadataDB + SnippetDB ingestion.

    All three stores share the same DuckDB file path for MetadataDB and SnippetDB;
    ChromaRetriever uses its own persist_dir on disk.

    Args:
        chunker:     StructuredChunker or compatible chunker.
        embedder:    MiniLMEmbedder (or any embedder with embed_passages).
        vector_store: ChromaRetriever with async upsert.
        metadata_db: MetadataDB for document-level tracking.
        snippet_db:  SnippetDB for sentence-level FTS.
        batch_size:  Number of chunks per vector-store upsert call.
    """

    def __init__(
        self,
        chunker: StructuredChunker,
        embedder: MiniLMEmbedder,
        vector_store: ChromaRetriever,
        metadata_db: MetadataDB,
        snippet_db: SnippetDB,
        batch_size: int = 64,
    ) -> None:
        self._chunker = chunker
        self._embedder = embedder
        self._vector_store = vector_store
        self._metadata_db = metadata_db
        self._snippet_db = snippet_db
        self._batch_size = batch_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ingest_document(self, doc: dict[str, str]) -> IngestionResult:
        """Ingest a single document dict.

        Minimum required key: ``text``.
        Optional: ``title``, ``url``, ``source``, ``content_type``, ``topic``, ``source_file``.
        """
        text = doc.get("text", "")
        if not text:
            log.warning("ingestion.skip.empty", source_file=doc.get("source_file", ""))
            return IngestionResult(doc_id="", chunk_count=0, snippet_count=0, skipped=True)

        checksum = _sha256(text)
        if self._metadata_db.document_exists_by_checksum(checksum):
            log.info("ingestion.skip.duplicate", source_file=doc.get("source_file", ""))
            return IngestionResult(doc_id="", chunk_count=0, snippet_count=0, skipped=True)

        doc_id = _stable_id(doc.get("source_file") or doc.get("title") or checksum)
        title = doc.get("title", "")
        source = doc.get("url") or doc.get("source", "")
        source_file = doc.get("source_file", "")
        content_type = doc.get("content_type", "")
        topic = doc.get("topic", "")

        # Chunking
        chunks = self._chunker.chunk_document(doc)
        log.info("ingestion.chunked", doc_id=doc_id, chunk_count=len(chunks))

        # Embedding
        texts = [c.text for c in chunks]
        embeddings = self._embedder.embed_passages(texts)
        for chunk, emb in zip(chunks, embeddings, strict=True):
            chunk.embedding = emb

        # Vector store upsert (batched)
        for i in range(0, len(chunks), self._batch_size):
            batch = chunks[i : i + self._batch_size]
            await self._vector_store.upsert(batch)

        # Snippet extraction
        sentences = self._extract_snippets(text)
        snippet_records = [
            {
                "id": f"{doc_id}_{idx}",
                "doc_id": doc_id,
                "text": s,
                "title": title,
                "topic": topic,
                "position": idx,
                "source": source,
            }
            for idx, s in enumerate(sentences)
        ]
        self._snippet_db.insert_snippets(snippet_records)

        # Metadata write
        self._metadata_db.insert_document(
            doc_id,
            title=title,
            source=source,
            source_file=source_file,
            content_type=content_type,
            topic=topic,
            word_count=len(text.split()),
            chunk_count=len(chunks),
            snippet_count=len(sentences),
            checksum=checksum,
        )

        log.info(
            "ingestion.done",
            doc_id=doc_id,
            chunk_count=len(chunks),
            snippet_count=len(sentences),
        )
        return IngestionResult(
            doc_id=doc_id,
            chunk_count=len(chunks),
            snippet_count=len(sentences),
        )

    async def ingest_documents(self, docs: list[dict[str, str]]) -> list[IngestionResult]:
        """Ingest a list of document dicts, returning one result per doc."""
        results = []
        for doc in docs:
            results.append(await self.ingest_document(doc))
        return results

    # ------------------------------------------------------------------
    # Snippet extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_snippets(
        text: str,
        min_len: int = _MIN_SNIPPET_LEN,
        max_len: int = _MAX_SNIPPET_LEN,
    ) -> list[str]:
        """Split *text* into sentences and return those within length bounds.

        Strips Markdown headings before splitting.
        """
        cleaned = re.sub(r"^#{1,6}\s+.*$", "", text, flags=re.MULTILINE)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        raw_sentences = _SENTENCE_RE.split(cleaned)
        return [s.strip() for s in raw_sentences if min_len <= len(s.strip()) <= max_len]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_id(seed: str) -> str:
    """Deterministic 16-char hex ID derived from *seed*."""
    return hashlib.md5(seed.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
