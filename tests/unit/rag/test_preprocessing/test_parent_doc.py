from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3] / "src"))

from preprocessing.chunker import ChunkerConfig, ParentDocChunker, _approx_tokens


def _doc(text: str) -> dict:
    return {
        "url": "https://help.example.com/page",
        "title": "Help Page",
        "section": "root",
        "text": text,
    }


def _long_section(n_words: int) -> str:
    return " ".join(f"word{i}" for i in range(n_words)) + "."


def test_child_chunks_smaller_than_parent():
    """Each child chunk must be smaller than the parent section."""
    text = "## Billing\n" + _long_section(300)
    chunker = ParentDocChunker(ChunkerConfig(max_tokens=512, min_tokens=5), child_chunk_size=64)
    chunks = chunker.chunk_document(_doc(text))
    assert len(chunks) > 0
    for c in chunks:
        assert _approx_tokens(c.text) <= 80, f"Child chunk too large: {_approx_tokens(c.text)}"


def test_parent_id_set_on_children():
    text = "## Getting Started\n" + _long_section(200)
    chunker = ParentDocChunker(ChunkerConfig(max_tokens=512, min_tokens=5), child_chunk_size=64)
    chunks = chunker.chunk_document(_doc(text))
    assert all(c.metadata.parent_id is not None for c in chunks)


def test_get_parent_returns_full_section():
    """get_parent(parent_id) must return text that covers all child text."""
    section_text = _long_section(200)
    text = "## API Reference\n" + section_text
    chunker = ParentDocChunker(ChunkerConfig(max_tokens=512, min_tokens=5), child_chunk_size=64)
    chunks = chunker.chunk_document(_doc(text))
    assert len(chunks) > 1

    parent_id = chunks[0].metadata.parent_id
    parent_text = chunker.get_parent(parent_id)
    assert parent_text is not None
    # Every child's first word should appear in the parent text
    for c in chunks:
        first_word = c.text.split()[0]
        assert first_word in parent_text, f"Child word {first_word!r} not found in parent"


def test_child_ids_unique():
    text = "## Section\n" + _long_section(300)
    chunker = ParentDocChunker(ChunkerConfig(max_tokens=512, min_tokens=5), child_chunk_size=64)
    chunks = chunker.chunk_document(_doc(text))
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))


def test_get_parent_unknown_id_returns_none():
    chunker = ParentDocChunker(ChunkerConfig(max_tokens=512, min_tokens=5))
    assert chunker.get_parent("nonexistent_id") is None


def test_empty_returns_no_chunks():
    chunker = ParentDocChunker(ChunkerConfig(max_tokens=512, min_tokens=5))
    assert chunker.chunk_document(_doc("")) == []


def test_multiple_sections_separate_parents():
    """Each heading section should produce a separate parent_id."""
    text = "## Section One\n" + _long_section(150) + "\n\n## Section Two\n" + _long_section(150)
    chunker = ParentDocChunker(ChunkerConfig(max_tokens=512, min_tokens=5), child_chunk_size=64)
    chunks = chunker.chunk_document(_doc(text))
    parent_ids = {c.metadata.parent_id for c in chunks}
    assert len(parent_ids) == 2, f"Expected 2 parent sections, got {len(parent_ids)}"
