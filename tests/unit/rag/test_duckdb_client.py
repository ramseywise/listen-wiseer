"""Unit tests for DuckDBVectorClient (RAG retrieval backend)."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src" / "rag_core"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from retrieval.duckdb_client import DuckDBVectorClient
from schemas.chunks import Chunk, ChunkMetadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DIMS = 384


def _make_chunk(
    chunk_id: str = "c1",
    subject: str = "aphex twin",
    text: str = "Aphex Twin is an electronic music producer from Cornwall.",
) -> Chunk:
    return Chunk(
        id=chunk_id,
        text=text,
        metadata=ChunkMetadata(
            url="wikipedia:Aphex Twin",
            title=subject,
            section="bio",
            doc_id=chunk_id,
        ),
    )


def _make_embedding(seed: float = 0.1) -> list[float]:
    return [seed] * _DIMS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> DuckDBVectorClient:
    """DuckDBVectorClient backed by a temp file DB (persists across open/close)."""
    db_path = str(tmp_path / "test.db")

    def factory(read_only: bool = False) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(db_path, read_only=read_only)

    return DuckDBVectorClient(connection_factory=factory)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_upsert_and_search_round_trip(client: DuckDBVectorClient):
    """Upsert a chunk, then search — should find it."""
    chunk = _make_chunk()
    embedding = _make_embedding(0.5)

    client.upsert_chunks([chunk], [embedding])
    results = client.search(query_vector=embedding, k=1, subject_filter="aphex twin")

    assert len(results) == 1
    assert results[0].chunk.id == "c1"
    assert results[0].chunk.text == chunk.text
    assert results[0].score == pytest.approx(1.0, abs=0.01)  # identical vector
    assert results[0].source == "vector"


def test_has_subject_true_after_upsert(client: DuckDBVectorClient):
    """has_subject returns True after upserting chunks for that subject."""
    assert client.has_subject("aphex twin") is False

    chunk = _make_chunk()
    client.upsert_chunks([chunk], [_make_embedding()])

    assert client.has_subject("aphex twin") is True


def test_has_subject_false_for_unknown(client: DuckDBVectorClient):
    """has_subject returns False for a subject with no chunks."""
    assert client.has_subject("unknown artist") is False


def test_subject_normalization(client: DuckDBVectorClient):
    """Subject is stored normalized (lowercase, stripped) from metadata.title."""
    chunk = _make_chunk(subject="  Aphex Twin  ")
    client.upsert_chunks([chunk], [_make_embedding()])

    # Normalized query should match
    assert client.has_subject("aphex twin") is True
    # Non-normalized should not match (DuckDB WHERE is case-sensitive)
    assert client.has_subject("Aphex Twin") is False


def test_search_empty_results_for_unknown_subject(client: DuckDBVectorClient):
    """Search with a subject filter for a non-existent subject returns empty."""
    chunk = _make_chunk(subject="aphex twin")
    client.upsert_chunks([chunk], [_make_embedding()])

    results = client.search(
        query_vector=_make_embedding(),
        k=5,
        subject_filter="miles davis",
    )
    assert results == []


def test_search_without_subject_filter(client: DuckDBVectorClient):
    """Search without subject_filter returns chunks across all subjects."""
    chunk_a = _make_chunk(chunk_id="c1", subject="aphex twin")
    chunk_b = _make_chunk(chunk_id="c2", subject="miles davis", text="Miles Davis was a jazz trumpeter.")
    client.upsert_chunks([chunk_a, chunk_b], [_make_embedding(0.3), _make_embedding(0.7)])

    results = client.search(query_vector=_make_embedding(0.7), k=10)
    assert len(results) == 2


def test_upsert_overwrites_existing_chunk(client: DuckDBVectorClient):
    """Upserting a chunk with the same ID replaces the old one."""
    chunk_v1 = _make_chunk(text="Version 1")
    chunk_v2 = _make_chunk(text="Version 2")

    client.upsert_chunks([chunk_v1], [_make_embedding(0.1)])
    client.upsert_chunks([chunk_v2], [_make_embedding(0.2)])

    results = client.search(query_vector=_make_embedding(0.2), k=1, subject_filter="aphex twin")
    assert len(results) == 1
    assert results[0].chunk.text == "Version 2"


def test_upsert_empty_list_is_noop(client: DuckDBVectorClient):
    """Upserting an empty list does nothing."""
    client.upsert_chunks([], [])
    assert client.has_subject("anything") is False
