from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "src"))

from preprocessing.chunker import AdjacencyChunker, ChunkerConfig


def _doc(text: str) -> dict:
    return {
        "url": "https://help.example.com/page",
        "title": "Help Page",
        "section": "root",
        "text": text,
    }


def _long_text(n_words: int) -> str:
    return " ".join(f"word{i}" for i in range(n_words))


@pytest.fixture
def chunker() -> AdjacencyChunker:
    return AdjacencyChunker(ChunkerConfig(max_tokens=30, overlap_tokens=0, min_tokens=5))


def test_neighbors_middle_chunk(chunker: AdjacencyChunker):
    chunks = chunker.chunk_document(_doc(_long_text(200)))
    assert len(chunks) >= 3
    mid_id = chunks[1].id
    prev_id, next_id = chunker.neighbors(mid_id)
    assert prev_id == chunks[0].id
    assert next_id == chunks[2].id


def test_neighbors_first_chunk(chunker: AdjacencyChunker):
    chunks = chunker.chunk_document(_doc(_long_text(200)))
    prev_id, next_id = chunker.neighbors(chunks[0].id)
    assert prev_id is None
    assert next_id == chunks[1].id


def test_neighbors_last_chunk(chunker: AdjacencyChunker):
    chunks = chunker.chunk_document(_doc(_long_text(200)))
    prev_id, next_id = chunker.neighbors(chunks[-1].id)
    assert prev_id == chunks[-2].id
    assert next_id is None


def test_neighbors_before_chunk_raises():
    fresh = AdjacencyChunker(ChunkerConfig(max_tokens=30, min_tokens=5))
    with pytest.raises(RuntimeError, match="chunk_document"):
        fresh.neighbors("some_doc_chunk0")


def test_neighbors_bad_format_raises(chunker: AdjacencyChunker):
    chunker.chunk_document(_doc(_long_text(100)))
    with pytest.raises(ValueError, match="Bad chunk_id format"):
        chunker.neighbors("no_underscore_chunk_marker")


def test_chunk_ids_positional(chunker: AdjacencyChunker):
    """Chunk IDs must end with _chunk0, _chunk1, etc."""
    chunks = chunker.chunk_document(_doc(_long_text(200)))
    for i, chunk in enumerate(chunks):
        assert chunk.id.endswith(f"_chunk{i}"), f"Unexpected id {chunk.id!r} at index {i}"


def test_empty_returns_no_chunks(chunker: AdjacencyChunker):
    assert chunker.chunk_document(_doc("")) == []
