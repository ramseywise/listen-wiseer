from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3] / "src"))

from preprocessing.chunker import ChunkerConfig, FixedChunker, OverlappingChunker


def _doc(text: str) -> dict:
    return {
        "url": "https://help.example.com/page",
        "title": "Help Page",
        "section": "root",
        "text": text,
    }


def _long_text(n_words: int) -> str:
    return " ".join(f"word{i}" for i in range(n_words))


# ---------------------------------------------------------------------------
# FixedChunker
# ---------------------------------------------------------------------------


def test_fixed_empty_returns_no_chunks():
    chunker = FixedChunker(ChunkerConfig(max_tokens=50, min_tokens=5))
    assert chunker.chunk_document(_doc("")) == []


def test_fixed_short_text_returns_one_chunk():
    chunker = FixedChunker(ChunkerConfig(max_tokens=100, min_tokens=5))
    chunks = chunker.chunk_document(_doc("short article about logging in"))
    assert len(chunks) == 1


def test_fixed_no_overlap():
    """Adjacent fixed chunks must share no words."""
    chunker = FixedChunker(ChunkerConfig(max_tokens=30, overlap_tokens=0, min_tokens=5))
    text = _long_text(200)
    chunks = chunker.chunk_document(_doc(text))
    assert len(chunks) > 1
    for i in range(len(chunks) - 1):
        words_a = set(chunks[i].text.split())
        words_b = set(chunks[i + 1].text.split())
        assert words_a.isdisjoint(words_b), f"Overlap found between chunk {i} and {i + 1}"


def test_fixed_chunk_ids_unique():
    chunker = FixedChunker(ChunkerConfig(max_tokens=30, min_tokens=5))
    chunks = chunker.chunk_document(_doc(_long_text(200)))
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))


def test_fixed_metadata_preserved():
    chunker = FixedChunker(ChunkerConfig(max_tokens=100, min_tokens=5))
    chunks = chunker.chunk_document(_doc("content for metadata test article"))
    assert chunks[0].metadata.url == "https://help.example.com/page"
    assert chunks[0].metadata.title == "Help Page"


# ---------------------------------------------------------------------------
# OverlappingChunker
# ---------------------------------------------------------------------------


def test_overlapping_boundary_words_shared():
    """Tail of chunk N must appear in head of chunk N+1."""
    chunker = OverlappingChunker(ChunkerConfig(max_tokens=30, overlap_tokens=8, min_tokens=5))
    text = _long_text(200)
    chunks = chunker.chunk_document(_doc(text))
    assert len(chunks) > 1
    for i in range(len(chunks) - 1):
        words_a = set(chunks[i].text.split()[-12:])
        words_b = set(chunks[i + 1].text.split()[:12])
        assert words_a & words_b, f"Expected overlap between chunk {i} and {i + 1}"


def test_overlapping_chunk_ids_unique():
    chunker = OverlappingChunker(ChunkerConfig(max_tokens=30, overlap_tokens=8, min_tokens=5))
    chunks = chunker.chunk_document(_doc(_long_text(200)))
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))


def test_overlapping_empty_returns_no_chunks():
    chunker = OverlappingChunker(ChunkerConfig(max_tokens=50, min_tokens=5))
    assert chunker.chunk_document(_doc("")) == []
