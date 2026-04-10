"""Document-level metadata store backed by DuckDB.

Tracks every document ingested through the pipeline: title, source,
word/chunk/snippet counts, ingest timestamp, and a SHA-256 checksum
for idempotent re-ingestion.

One DuckDB file is shared with SnippetDB — each uses a separate table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from utils.logging import get_logger

log = get_logger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,
    title         TEXT,
    source        TEXT,
    source_file   TEXT,
    content_type  TEXT,
    topic         TEXT,
    word_count    INTEGER,
    chunk_count   INTEGER,
    snippet_count INTEGER,
    ingest_time   TEXT,
    checksum      TEXT UNIQUE
)
"""


class MetadataDB:
    """Document-level metadata store.

    One persistent DuckDB connection shared across all operations.
    Call ``close()`` or use as a context manager when done.
    """

    def __init__(self, db_path: str) -> None:
        import duckdb

        self._db_path = db_path
        self._conn = duckdb.connect(db_path)
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._conn.execute(_DDL)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def insert_document(
        self,
        doc_id: str,
        *,
        title: str,
        source: str,
        source_file: str,
        content_type: str,
        topic: str,
        word_count: int,
        chunk_count: int,
        snippet_count: int,
        checksum: str,
    ) -> None:
        """Insert a document record. Skips silently if checksum already exists."""
        ingest_time = datetime.now(tz=UTC).isoformat()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO documents
                (doc_id, title, source, source_file, content_type, topic,
                 word_count, chunk_count, snippet_count, ingest_time, checksum)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                doc_id,
                title,
                source,
                source_file,
                content_type,
                topic,
                word_count,
                chunk_count,
                snippet_count,
                ingest_time,
                checksum,
            ],
        )
        log.info(
            "metadata_db.insert",
            doc_id=doc_id,
            title=title,
            chunk_count=chunk_count,
            snippet_count=snippet_count,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def document_exists_by_checksum(self, checksum: str) -> bool:
        """Return True if a document with this checksum has already been ingested."""
        row = self._conn.execute(
            "SELECT doc_id FROM documents WHERE checksum = ?", [checksum]
        ).fetchone()
        return row is not None

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """Return the document record for *doc_id*, or None if not found."""
        row = self._conn.execute("SELECT * FROM documents WHERE doc_id = ?", [doc_id]).fetchone()
        if row is None:
            return None
        cols = [
            "doc_id",
            "title",
            "source",
            "source_file",
            "content_type",
            "topic",
            "word_count",
            "chunk_count",
            "snippet_count",
            "ingest_time",
            "checksum",
        ]
        return dict(zip(cols, row, strict=True))

    def list_documents(self) -> list[dict[str, Any]]:
        """Return all document records ordered by ingest_time."""
        rows = self._conn.execute("SELECT * FROM documents ORDER BY ingest_time").fetchall()
        cols = [
            "doc_id",
            "title",
            "source",
            "source_file",
            "content_type",
            "topic",
            "word_count",
            "chunk_count",
            "snippet_count",
            "ingest_time",
            "checksum",
        ]
        return [dict(zip(cols, row, strict=True)) for row in rows]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> MetadataDB:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
