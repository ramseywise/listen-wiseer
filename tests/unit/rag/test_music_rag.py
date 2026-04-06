"""Tests for MusicRAG orchestrator — all dependencies mocked."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src" / "rag_core"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from schemas.chunks import Chunk, ChunkMetadata
from schemas.retrieval import RetrievalResult


def _make_chunk(chunk_id: str = "c1", text: str = "Some text about the artist.") -> Chunk:
    return Chunk(
        id=chunk_id,
        text=text,
        metadata=ChunkMetadata(
            url="https://en.wikipedia.org/wiki/Aphex_Twin",
            title="aphex twin",
            section="bio",
            doc_id="doc1",
        ),
    )


def _build_rag(
    *,
    has_subject: bool = False,
    search_results: list[RetrievalResult] | None = None,
    wikipedia_content: str | None = "Richard David James...",
    tavily_content: str | None = None,
    chunks: list[Chunk] | None = None,
):
    """Build a MusicRAG with all dependencies mocked."""
    from orchestration.music_rag import MusicRAG

    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1] * 384
    mock_embedder.embed_passages.return_value = [[0.1] * 384]

    mock_client = MagicMock()
    mock_client.has_subject.return_value = has_subject
    mock_client.search.return_value = search_results or []

    rag = MusicRAG(embedder=mock_embedder, client=mock_client)

    # Mock the chunker to return controlled chunks
    mock_chunker = MagicMock()
    mock_chunker.chunk_document.return_value = chunks or [_make_chunk()]
    rag._chunker = mock_chunker

    return rag, mock_embedder, mock_client, mock_chunker, wikipedia_content, tavily_content


# ---------------------------------------------------------------------------
# Cache hit
# ---------------------------------------------------------------------------


def test_cache_hit_skips_fetch():
    """When has_subject is True, skip Wikipedia/Tavily fetch."""
    results = [RetrievalResult(chunk=_make_chunk(), score=0.9)]
    rag, mock_embedder, mock_client, mock_chunker, _, _ = _build_rag(
        has_subject=True,
        search_results=results,
    )

    with patch("orchestration.music_rag.fetch_wikipedia") as mock_wiki:
        context = rag.get_context("Aphex Twin")

    mock_wiki.assert_not_called()
    mock_client.has_subject.assert_called_once_with("aphex twin")
    mock_embedder.embed_query.assert_called_once_with("Aphex Twin")
    mock_client.search.assert_called_once()
    assert "Some text about the artist." in context


def test_cache_hit_returns_multiple_passages():
    """Multiple search results are joined with separator."""
    results = [
        RetrievalResult(chunk=_make_chunk("c1", "Passage one."), score=0.9),
        RetrievalResult(chunk=_make_chunk("c2", "Passage two."), score=0.8),
    ]
    rag, _, _, _, _, _ = _build_rag(has_subject=True, search_results=results)

    context = rag.get_context("Aphex Twin")

    assert "Passage one." in context
    assert "Passage two." in context
    assert "---" in context


# ---------------------------------------------------------------------------
# Cache miss — Wikipedia fetch
# ---------------------------------------------------------------------------


def test_cache_miss_fetches_wikipedia_and_ingests():
    """Cache miss → fetch Wikipedia → chunk → embed → upsert → search."""
    search_results = [RetrievalResult(chunk=_make_chunk(), score=0.85)]
    rag, mock_embedder, mock_client, mock_chunker, wiki_content, _ = _build_rag(
        has_subject=False,
        search_results=search_results,
    )
    # After ingest, has_subject still returns False for the initial check,
    # but search returns results
    with (
        patch("orchestration.music_rag.fetch_wikipedia", return_value=wiki_content),
        patch("orchestration.music_rag.fetch_tavily") as mock_tavily,
    ):
        context = rag.get_context("Aphex Twin")

    mock_tavily.assert_not_called()
    mock_chunker.chunk_document.assert_called_once()
    mock_embedder.embed_passages.assert_called_once()
    mock_client.upsert_chunks.assert_called_once()
    assert "Some text about the artist." in context


# ---------------------------------------------------------------------------
# Cache miss — Tavily fallback
# ---------------------------------------------------------------------------


def test_cache_miss_falls_back_to_tavily():
    """Wikipedia returns None → Tavily used as fallback."""
    search_results = [RetrievalResult(chunk=_make_chunk(), score=0.8)]
    rag, _, mock_client, mock_chunker, _, tavily_content = _build_rag(
        has_subject=False,
        search_results=search_results,
        wikipedia_content=None,
        tavily_content="Tavily content about the artist.",
    )

    with (
        patch("orchestration.music_rag.fetch_wikipedia", return_value=None),
        patch("orchestration.music_rag.fetch_tavily", return_value="Tavily content about the artist."),
    ):
        context = rag.get_context("Aphex Twin")

    mock_chunker.chunk_document.assert_called_once()
    mock_client.upsert_chunks.assert_called_once()
    assert "Some text about the artist." in context


# ---------------------------------------------------------------------------
# No content found
# ---------------------------------------------------------------------------


def test_no_content_returns_fallback_message():
    """Neither Wikipedia nor Tavily returns content → fallback message."""
    from orchestration.music_rag import _NO_CONTENT_MESSAGE

    rag, _, mock_client, _, _, _ = _build_rag(has_subject=False)

    with (
        patch("orchestration.music_rag.fetch_wikipedia", return_value=None),
        patch("orchestration.music_rag.fetch_tavily", return_value=None),
    ):
        context = rag.get_context("xyznonexistent")

    assert context == _NO_CONTENT_MESSAGE
    mock_client.upsert_chunks.assert_not_called()


def test_empty_search_results_returns_fallback():
    """Cache hit but search returns empty → fallback message."""
    from orchestration.music_rag import _NO_CONTENT_MESSAGE

    rag, _, _, _, _, _ = _build_rag(has_subject=True, search_results=[])

    context = rag.get_context("Aphex Twin")

    assert context == _NO_CONTENT_MESSAGE


# ---------------------------------------------------------------------------
# Subject normalization
# ---------------------------------------------------------------------------


def test_subject_normalized():
    """Subject is stripped and lowercased before lookup."""
    results = [RetrievalResult(chunk=_make_chunk(), score=0.9)]
    rag, _, mock_client, _, _, _ = _build_rag(has_subject=True, search_results=results)

    rag.get_context("  Aphex Twin  ")

    mock_client.has_subject.assert_called_once_with("aphex twin")
    mock_client.search.assert_called_once()
    call_kwargs = mock_client.search.call_args[1]
    assert call_kwargs["subject_filter"] == "aphex twin"


# ---------------------------------------------------------------------------
# Chunker receives correct doc dict
# ---------------------------------------------------------------------------


def test_ingest_passes_correct_doc_to_chunker():
    """The doc dict passed to chunker has expected keys."""
    search_results = [RetrievalResult(chunk=_make_chunk(), score=0.85)]
    rag, _, _, mock_chunker, _, _ = _build_rag(
        has_subject=False,
        search_results=search_results,
    )

    with (
        patch("orchestration.music_rag.fetch_wikipedia", return_value="Wiki content"),
        patch("orchestration.music_rag.fetch_tavily"),
    ):
        rag.get_context("Radiohead")

    doc = mock_chunker.chunk_document.call_args[0][0]
    assert doc["title"] == "radiohead"
    assert doc["section"] == "bio"
    assert doc["text"] == "Wiki content"
    assert "Radiohead" in doc["url"]
