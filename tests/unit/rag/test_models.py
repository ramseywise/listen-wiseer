from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src" / "rag_core"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from schemas.chunks import Chunk, ChunkMetadata
from schemas.conversation import initial_state
from schemas.retrieval import GradedChunk, Intent, RetrievalResult

from evals.tasks.models import GoldenSample, RetrievalMetrics


def _make_metadata(**kwargs) -> ChunkMetadata:
    defaults = {
        "url": "https://help.example.com/article/1",
        "title": "Getting started",
        "section": "intro",
        "doc_id": "abc123",
    }
    return ChunkMetadata(**{**defaults, **kwargs})


def _make_chunk(**kwargs) -> Chunk:
    defaults = {
        "id": "chunk-001",
        "text": "This is a test chunk.",
        "metadata": _make_metadata(),
    }
    return Chunk(**{**defaults, **kwargs})


# ---------------------------------------------------------------------------
# ChunkMetadata
# ---------------------------------------------------------------------------


def test_chunk_metadata_defaults():
    m = _make_metadata()
    assert m.language == "en"
    assert m.url == "https://help.example.com/article/1"


def test_chunk_metadata_custom_language():
    m = _make_metadata(language="fr")
    assert m.language == "fr"


# ---------------------------------------------------------------------------
# Chunk
# ---------------------------------------------------------------------------


def test_chunk_embedding_default_none():
    c = _make_chunk()
    assert c.embedding is None


def test_chunk_with_embedding():
    c = _make_chunk(embedding=[0.1, 0.2, 0.3])
    assert len(c.embedding) == 3


# ---------------------------------------------------------------------------
# Intent
# ---------------------------------------------------------------------------


def test_intent_values():
    assert Intent.ARTIST_INFO == "artist_info"
    assert Intent.GENRE_INFO == "genre_info"
    assert Intent.HISTORY == "history"
    assert Intent.CHIT_CHAT == "chit_chat"
    assert Intent.OUT_OF_SCOPE == "out_of_scope"


# ---------------------------------------------------------------------------
# RetrievalResult
# ---------------------------------------------------------------------------


def test_retrieval_result_default_source():
    r = RetrievalResult(chunk=_make_chunk(), score=0.85)
    assert r.source == "hybrid"


def test_retrieval_result_custom_source():
    r = RetrievalResult(chunk=_make_chunk(), score=0.7, source="bm25")
    assert r.source == "bm25"


# ---------------------------------------------------------------------------
# GradedChunk
# ---------------------------------------------------------------------------


def test_graded_chunk():
    g = GradedChunk(chunk=_make_chunk(), score=0.9, relevant=True)
    assert g.relevant is True
    assert g.score == 0.9


# ---------------------------------------------------------------------------
# RAGState / initial_state
# ---------------------------------------------------------------------------


def test_initial_state_defaults():
    state = initial_state("who is Aphex Twin?")
    assert state["query"] == "who is Aphex Twin?"
    assert state["standalone_query"] == ""
    assert state["intent"] == Intent.ARTIST_INFO
    assert state["query_variants"] == []
    assert state["retrieved_chunks"] == []
    assert state["graded_chunks"] == []
    assert state["response"] == ""
    assert state["confident"] is True
    assert state["retry_count"] == 0
    assert state["trace_id"] == ""


def test_initial_state_with_trace_id():
    state = initial_state("test query", trace_id="trace-abc")
    assert state["trace_id"] == "trace-abc"


# ---------------------------------------------------------------------------
# GoldenSample
# ---------------------------------------------------------------------------


def test_golden_sample_defaults():
    s = GoldenSample(
        query_id="ticket_001",
        query="How do I export data?",
        expected_doc_url="https://help.example.com/export",
    )
    assert s.language == "da"
    assert s.difficulty == "easy"
    assert s.validation_level == "silver"
    assert s.relevant_chunk_ids == []
    assert s.source_ticket_id == ""


def test_golden_sample_gold_tier():
    s = GoldenSample(
        query_id="ticket_002",
        query="Configure SSO",
        expected_doc_url="https://help.example.com/sso",
        relevant_chunk_ids=["chunk-1", "chunk-2"],
        validation_level="gold",
        difficulty="hard",
    )
    assert len(s.relevant_chunk_ids) == 2
    assert s.validation_level == "gold"


# ---------------------------------------------------------------------------
# RetrievalMetrics
# ---------------------------------------------------------------------------


def test_retrieval_metrics():
    m = RetrievalMetrics(hit_rate_at_k=0.72, mrr=0.58, k=5, n_queries=100)
    assert m.hit_rate_at_k == 0.72
    assert m.mrr == 0.58
    assert m.k == 5
    assert m.n_queries == 100
