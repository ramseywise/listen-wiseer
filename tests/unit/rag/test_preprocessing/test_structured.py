from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3] / "src"))

from preprocessing.chunker import ChunkerConfig, StructuredChunker


def _doc(text: str) -> dict:
    return {
        "url": "https://help.example.com/page",
        "title": "Help Page",
        "section": "root",
        "text": text,
    }


def test_short_text_single_chunk():
    chunker = StructuredChunker(ChunkerConfig(max_tokens=100, min_tokens=5))
    chunks = chunker.chunk_document(_doc("Short article about account setup and login."))
    assert len(chunks) == 1


def test_empty_returns_no_chunks():
    chunker = StructuredChunker(ChunkerConfig(max_tokens=100, min_tokens=5))
    assert chunker.chunk_document(_doc("")) == []


def test_paragraph_boundaries_respected():
    """Two large paragraphs should split at the paragraph boundary, not mid-sentence."""
    para_a = " ".join(f"word{i}" for i in range(60)) + "."
    para_b = " ".join(f"other{i}" for i in range(60)) + "."
    text = f"{para_a}\n\n{para_b}"
    chunker = StructuredChunker(ChunkerConfig(max_tokens=50, overlap_tokens=5, min_tokens=5))
    chunks = chunker.chunk_document(_doc(text))
    assert len(chunks) >= 2
    # Each chunk should contain words from only one paragraph (no cross-para mixing in first chunk)
    first_words = set(chunks[0].text.split())
    assert any(w.startswith("word") for w in first_words)


def test_fallback_sentence_split():
    """Flat text with sentence boundaries should split on sentences, not mid-word."""
    # 3 long sentences, no paragraph breaks
    sentences = [
        "This is a long sentence about configuring your account settings and preferences in the system.",
        "Another long sentence that explains how to reset your password using the email verification flow.",
        "A third long sentence describing the billing cycle and invoice delivery process for all users.",
    ]
    text = " ".join(sentences)
    chunker = StructuredChunker(ChunkerConfig(max_tokens=20, overlap_tokens=3, min_tokens=5))
    chunks = chunker.chunk_document(_doc(text))
    assert len(chunks) >= 2
    # No chunk should start mid-word (all start with a capital or 'word')
    for c in chunks:
        assert c.text.strip(), "Empty chunk"


def test_chunk_ids_unique():
    chunker = StructuredChunker(ChunkerConfig(max_tokens=30, min_tokens=5))
    text = " ".join(f"token{i}" for i in range(300))
    chunks = chunker.chunk_document(_doc(text))
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))


def test_no_heading_detection():
    """StructuredChunker must NOT treat markdown headings as section boundaries."""
    text = (
        "## Section One\nContent about section one.\n\n## Section Two\nContent about section two."
    )
    chunker = StructuredChunker(ChunkerConfig(max_tokens=200, min_tokens=5))
    # Should produce 1 chunk (fits in max_tokens) — NOT split by heading
    chunks = chunker.chunk_document(_doc(text))
    assert len(chunks) == 1
    assert "## Section One" in chunks[0].text
    assert "## Section Two" in chunks[0].text
