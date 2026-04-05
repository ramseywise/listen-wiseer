from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).parents[2]))

from preprocessing.chunker import ChunkerConfig, HtmlAwareChunker, _approx_tokens


@pytest.fixture
def chunker() -> HtmlAwareChunker:
    return HtmlAwareChunker(ChunkerConfig(max_tokens=100, overlap_tokens=10, min_tokens=5))


def _doc(text: str, section: str = "root") -> dict:
    return {
        "url": "https://help.example.com/page",
        "title": "Help Page",
        "section": section,
        "text": text,
    }


# ---------------------------------------------------------------------------
# Basic section splitting
# ---------------------------------------------------------------------------


def test_single_section_returns_one_chunk(chunker):
    doc = _doc("This is a short help article about logging in.")
    chunks = chunker.chunk_document(doc)
    assert len(chunks) == 1
    assert "logging in" in chunks[0].text


def test_markdown_headings_split_into_sections(chunker):
    text = (
        "## Getting Started\n"
        "First steps to set up your account.\n\n"
        "## Troubleshooting\n"
        "Common issues and how to fix them."
    )
    chunks = chunker.chunk_document(_doc(text))
    assert len(chunks) == 2
    texts = [c.text for c in chunks]
    assert any("Getting Started" in t or "set up" in t for t in texts)
    assert any("Troubleshooting" in t or "fix them" in t for t in texts)


def test_section_metadata_reflects_heading(chunker):
    billing_body = "Invoices are generated at the end of each billing period and sent by email."
    api_body = "Use the REST API to automate exports. Authentication is via API key in headers."
    text = f"## Billing\n{billing_body}\n\n## API\n{api_body}"
    chunks = chunker.chunk_document(_doc(text, section="docs"))
    sections = [c.metadata.section for c in chunks]
    assert any("Billing" in s for s in sections)
    assert any("API" in s for s in sections)


def test_chunk_url_and_title_preserved(chunker):
    text = "This help article explains how to configure your account settings and preferences."
    chunks = chunker.chunk_document(_doc(text))
    assert chunks[0].metadata.url == "https://help.example.com/page"
    assert chunks[0].metadata.title == "Help Page"


def test_empty_text_returns_no_chunks(chunker):
    chunks = chunker.chunk_document(_doc(""))
    assert chunks == []


# ---------------------------------------------------------------------------
# Recursive fallback — oversized section
# ---------------------------------------------------------------------------


def _long_section(n_words: int) -> str:
    """Generate a section with n_words words separated by paragraph breaks."""
    sentences = []
    for i in range(0, n_words, 10):
        sentences.append(" ".join(f"word{j}" for j in range(i, min(i + 10, n_words))) + ".")
    # Group into paragraphs of ~3 sentences
    paras = []
    for i in range(0, len(sentences), 3):
        paras.append(" ".join(sentences[i : i + 3]))
    return "\n\n".join(paras)


def test_oversized_section_splits_into_multiple_chunks():
    # max_tokens=50 → a 400-word section must split
    chunker = HtmlAwareChunker(ChunkerConfig(max_tokens=50, overlap_tokens=5, min_tokens=5))
    text = _long_section(400)
    chunks = chunker.chunk_document(_doc(text))
    assert len(chunks) > 1, "Oversized section should produce multiple chunks"
    for c in chunks:
        assert _approx_tokens(c.text) <= 55, f"Chunk too large: {_approx_tokens(c.text)} tokens"


def test_recursive_split_overlap_preserved():
    """Chunks from a recursive split should share some words at boundaries."""
    chunker = HtmlAwareChunker(ChunkerConfig(max_tokens=30, overlap_tokens=5, min_tokens=5))
    # 120-word flat text, no headings, no paragraph breaks → hits hard split
    text = " ".join(f"token{i}" for i in range(120))
    chunks = chunker.chunk_document(_doc(text))
    assert len(chunks) >= 2

    # Check overlap: last few words of chunk N appear in chunk N+1
    for i in range(len(chunks) - 1):
        words_a = set(chunks[i].text.split()[-8:])
        words_b = set(chunks[i + 1].text.split()[:8])
        assert words_a & words_b, (
            f"Expected overlap between chunk {i} and {i + 1}; "
            f"tail={list(words_a)[:3]}, head={list(words_b)[:3]}"
        )


def test_short_doc_no_splitting():
    """A document short enough to fit in one chunk must not be split."""
    chunker = HtmlAwareChunker(ChunkerConfig(max_tokens=200, overlap_tokens=20, min_tokens=5))
    text = "Short article. " * 5
    chunks = chunker.chunk_document(_doc(text))
    assert len(chunks) == 1


# ---------------------------------------------------------------------------
# IDs and deduplication
# ---------------------------------------------------------------------------


def test_chunk_ids_are_unique():
    chunker = HtmlAwareChunker(ChunkerConfig(max_tokens=50, overlap_tokens=5, min_tokens=5))
    text = _long_section(300)
    chunks = chunker.chunk_document(_doc(text))
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids)), "Chunk IDs must be unique"


def test_doc_id_is_deterministic():
    chunker = HtmlAwareChunker(ChunkerConfig(min_tokens=5))
    doc = _doc("Stable content for this determinism test article.")
    chunks1 = chunker.chunk_document(doc)
    chunks2 = chunker.chunk_document(doc)
    assert chunks1[0].metadata.doc_id == chunks2[0].metadata.doc_id
