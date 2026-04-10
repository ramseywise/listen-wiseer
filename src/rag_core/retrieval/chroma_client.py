"""ChromaDB retrieval backend for RAG chunks.

Persistent HNSW index via chromadb.PersistentClient.
Hybrid score = bm25_weight * term_overlap + vector_weight * cosine_similarity,
mirroring the DuckDB backend's interface for drop-in substitution.

Requires: uv add chromadb
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from schemas.chunks import Chunk, ChunkMetadata
from schemas.retrieval import RetrievalResult

from retrieval.scoring import term_overlap
from utils.logging import get_logger

log = get_logger(__name__)

_DEFAULT_PERSIST_DIR = ".chroma"
_DEFAULT_COLLECTION = "music-rag-chunks"
_BM25_WEIGHT = 0.3
_VECTOR_WEIGHT = 0.7


def _chroma_distance_to_score(distance: float) -> float:
    """Convert Chroma cosine distance [0, 2] → similarity [0, 1].

    Chroma uses cosine *distance* = 1 - cosine_similarity, so we invert.
    Clamped to [0, 1] to handle floating-point edge cases.
    """
    return max(0.0, min(1.0, 1.0 - distance))


class ChromaRetriever:
    """Persistent ChromaDB retriever with hybrid vector + term-overlap scoring.

    Data is persisted to ``persist_dir`` on disk — no Docker required.

    Hybrid score formula:
        score = bm25_weight * term_overlap(query, text)
              + vector_weight * chroma_cosine_similarity
    """

    def __init__(
        self,
        persist_dir: str | Path = _DEFAULT_PERSIST_DIR,
        collection_name: str = _DEFAULT_COLLECTION,
        bm25_weight: float = _BM25_WEIGHT,
        vector_weight: float = _VECTOR_WEIGHT,
    ) -> None:
        self._persist_dir = str(persist_dir)
        self._collection_name = collection_name
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self._client: Any | None = None
        self._collection: Any | None = None

    def _get_collection(self) -> Any:
        if self._collection is None:
            import chromadb  # type: ignore[import-untyped]

            if self._client is None:
                log.info("chroma.client.init", persist_dir=self._persist_dir)
                self._client = chromadb.PersistentClient(path=self._persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    async def upsert(self, chunks: list[Chunk]) -> None:
        """Upsert chunks into the Chroma collection.

        Chunks without embeddings are skipped with a warning.
        """
        collection = self._get_collection()
        if not chunks:
            return

        ids: list[str] = []
        embeddings: list[list[float]] = []
        documents: list[str] = []
        metadatas: list[dict] = []

        for chunk in chunks:
            if chunk.embedding is None:
                log.warning("chroma.upsert.missing_embedding", chunk_id=chunk.id)
                continue
            ids.append(chunk.id)
            embeddings.append(chunk.embedding)
            documents.append(chunk.text)
            meta = chunk.metadata.model_dump()
            # Chroma metadata values must be str | int | float | bool
            metadatas.append({k: str(v) for k, v in meta.items() if v is not None})

        if ids:
            collection.upsert(
                ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
            )
            log.info("chroma.upsert.done", n=len(ids), collection=self._collection_name)

    # Sync alias kept for MusicRAG compatibility
    def upsert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Sync upsert used by MusicRAG._ingest — attaches embeddings then calls upsert."""
        import asyncio

        for chunk, emb in zip(chunks, embeddings, strict=True):
            chunk.embedding = emb

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Inside an async context (e.g. tests with pytest-asyncio)
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self.upsert(chunks))
                    future.result()
            else:
                loop.run_until_complete(self.upsert(chunks))
        except RuntimeError:
            asyncio.run(self.upsert(chunks))

    async def search(
        self,
        query_text: str,
        query_vector: list[float],
        k: int = 10,
        metadata_filter: dict | None = None,
    ) -> list[RetrievalResult]:
        """Hybrid vector + term-overlap search.

        Args:
            query_text: Raw query string for term-overlap scoring.
            query_vector: Query embedding.
            k: Maximum results to return.
            metadata_filter: Optional equality filters applied in Chroma.

        Returns:
            Results sorted by descending hybrid score.
        """
        collection = self._get_collection()

        where: dict | None = None
        if metadata_filter:
            conditions = [{key: {"$eq": val}} for key, val in metadata_filter.items()]
            where = {"$and": conditions} if len(conditions) > 1 else conditions[0]

        count = collection.count()
        if count == 0:
            return []

        resp = collection.query(
            query_embeddings=[query_vector],
            n_results=min(k, count),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        results: list[RetrievalResult] = []
        for chunk_id, text, meta, dist in zip(
            resp["ids"][0],
            resp["documents"][0],
            resp["metadatas"][0],
            resp["distances"][0],
            strict=False,
        ):
            vec_score = _chroma_distance_to_score(dist)
            kw_score = term_overlap(query_text, text)
            hybrid_score = self.bm25_weight * kw_score + self.vector_weight * vec_score

            # Reconstruct ChunkMetadata — tolerate missing optional fields
            meta_clean = {k: v for k, v in meta.items() if v not in (None, "None")}
            chunk = Chunk(
                id=chunk_id,
                text=text,
                metadata=ChunkMetadata(**meta_clean),
            )
            results.append(RetrievalResult(chunk=chunk, score=hybrid_score, source="hybrid"))

        results.sort(key=lambda r: r.score, reverse=True)
        log.info(
            "chroma.search.done",
            n_results=len(results),
            query=query_text[:60],
        )
        return results[:k]

    # Sync alias used by MusicRAG
    def search_sync(
        self,
        query_text: str,
        query_vector: list[float],
        k: int = 5,
        subject_filter: str | None = None,
    ) -> list[RetrievalResult]:
        """Synchronous search wrapper for MusicRAG.get_context."""
        import asyncio

        metadata_filter = {"title": subject_filter} if subject_filter else None
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.search(query_text, query_vector, k, metadata_filter),
                    )
                    return future.result()
            return loop.run_until_complete(
                self.search(query_text, query_vector, k, metadata_filter)
            )
        except RuntimeError:
            return asyncio.run(self.search(query_text, query_vector, k, metadata_filter))

    def has_subject(self, subject: str) -> bool:
        """Return True if any chunks with title==subject exist in the collection."""
        collection = self._get_collection()
        try:
            result = collection.get(
                where={"title": {"$eq": subject}},
                limit=1,
            )
            return len(result["ids"]) > 0
        except Exception as exc:  # noqa: BLE001
            log.warning("chroma.has_subject.error", subject=subject, error=str(exc))
            return False
