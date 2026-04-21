"""DuckDB retrieval backend for RAG chunks.

Uses array_cosine_similarity (core DuckDB function, no vss extension needed)
for brute-force cosine search. Stores chunks in the rag_chunks table within
the shared listen_wiseer.db file.
"""

from __future__ import annotations

import duckdb
from schemas.chunks import Chunk, ChunkMetadata
from schemas.retrieval import RetrievalResult

from utils.logging import get_logger

log = get_logger(__name__)

_EMBEDDING_DIMS = 384


class DuckDBVectorClient:
    """DuckDB retrieval backend — stores chunks in rag_chunks table.

    Uses array_cosine_similarity (core DuckDB function) for brute-force cosine search.
    Shares listen_wiseer.db with the rest of the app via etl.db.get_connection.
    No vss extension needed at this scale (<10k chunks).

    Connection is opened/closed per operation to avoid holding DuckDB's
    single-writer lock during long-running sync or training operations.
    """

    def __init__(self, connection_factory: object | None = None) -> None:
        """Initialize the client.

        Args:
            connection_factory: Callable returning a DuckDB connection.
                Defaults to ``etl.db.get_connection`` (imports lazily to
                avoid circular imports in test environments).
        """
        if connection_factory is not None:
            self._connect = connection_factory  # type: ignore[assignment]
        else:
            from etl.db import get_connection
            self._connect = get_connection  # type: ignore[assignment]

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        """Open a fresh connection for a single operation."""
        return self._connect(read_only=False)  # type: ignore[operator]

    def _ensure_table(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Create rag_chunks table if it doesn't exist (idempotent)."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rag_chunks (
                chunk_id    VARCHAR PRIMARY KEY,
                subject     VARCHAR NOT NULL,
                section     VARCHAR DEFAULT 'bio',
                source_url  VARCHAR DEFAULT '',
                text        VARCHAR NOT NULL,
                embedding   FLOAT[384],
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def search(
        self,
        query_vector: list[float],
        k: int = 5,
        subject_filter: str | None = None,
    ) -> list[RetrievalResult]:
        """Query rag_chunks and return top-k results ranked by cosine similarity.

        Args:
            query_vector: 384-dim embedding of the query.
            k: Number of results to return.
            subject_filter: If set, only return chunks for this normalized subject.
        """
        conn = self._get_conn()
        try:
            self._ensure_table(conn)

            if subject_filter:
                rows = conn.execute(
                    """
                    SELECT chunk_id, subject, section, source_url, text,
                           array_cosine_similarity(embedding, $1::FLOAT[384]) AS score
                    FROM rag_chunks
                    WHERE subject = $2
                    ORDER BY score DESC
                    LIMIT $3
                    """,
                    [query_vector, subject_filter, k],
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT chunk_id, subject, section, source_url, text,
                           array_cosine_similarity(embedding, $1::FLOAT[384]) AS score
                    FROM rag_chunks
                    ORDER BY score DESC
                    LIMIT $2
                    """,
                    [query_vector, k],
                ).fetchall()

            results: list[RetrievalResult] = []
            for chunk_id, subject, section, source_url, text, score in rows:
                chunk = Chunk(
                    id=chunk_id,
                    text=text,
                    metadata=ChunkMetadata(
                        url=source_url,
                        title=subject,
                        section=section,
                        doc_id=chunk_id,
                    ),
                )
                results.append(RetrievalResult(chunk=chunk, score=float(score), source="vector"))

            log.info("duckdb.search.done", n_results=len(results), subject=subject_filter)
            return results
        finally:
            conn.close()

    def upsert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Bulk upsert chunks with precomputed embeddings.

        Uses DELETE + INSERT per chunk (DuckDB has no native UPSERT with arrays).
        """
        if not chunks:
            return

        conn = self._get_conn()
        try:
            self._ensure_table(conn)

            for chunk, embedding in zip(chunks, embeddings, strict=True):
                subject = chunk.metadata.title.strip().lower()
                conn.execute("DELETE FROM rag_chunks WHERE chunk_id = ?", [chunk.id])
                conn.execute(
                    """
                    INSERT INTO rag_chunks (chunk_id, subject, section, source_url, text, embedding)
                    VALUES (?, ?, ?, ?, ?, ?::FLOAT[384])
                    """,
                    [
                        chunk.id,
                        subject,
                        chunk.metadata.section,
                        chunk.metadata.url,
                        chunk.text,
                        embedding,
                    ],
                )

            log.info("duckdb.upsert.done", n_chunks=len(chunks))
        finally:
            conn.close()

    def has_subject(self, subject: str) -> bool:
        """Check if any chunks exist for the given normalized subject.

        Args:
            subject: Normalized subject string (lowercase, stripped).
        """
        conn = self._get_conn()
        try:
            self._ensure_table(conn)
            row = conn.execute(
                "SELECT COUNT(*) FROM rag_chunks WHERE subject = ?",
                [subject],
            ).fetchone()
            return row is not None and row[0] > 0
        finally:
            conn.close()
