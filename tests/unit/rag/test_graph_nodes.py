"""Unit tests for LangGraph query pipeline nodes.

Nodes are tested in isolation with synthetic RAGState dicts.
LLM calls (Anthropic) and OpenSearch calls are mocked.
QueryAnalyzer is NOT mocked — it is pure and has no I/O.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src" / "rag_core"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chunk(chunk_id: str = "c1", text: str = "Some relevant help text.") -> dict:
    """Build a synthetic Chunk-compatible dict."""
    from schemas.chunks import Chunk, ChunkMetadata

    return Chunk(
        id=chunk_id,
        text=text,
        metadata=ChunkMetadata(
            url="https://help.example.com/article/1",
            title="Article",
            section="general",
            doc_id="doc1",
        ),
    )


def _make_retrieval_result(chunk_id: str = "c1", score: float = 0.9):
    from schemas.retrieval import RetrievalResult

    return RetrievalResult(chunk=_make_chunk(chunk_id), score=score)


def _make_graded_chunk(chunk_id: str = "c1", score: float = 0.8, relevant: bool = True):
    from schemas.retrieval import GradedChunk

    return GradedChunk(chunk=_make_chunk(chunk_id), score=score, relevant=relevant)


def _base_state(**overrides) -> dict:
    """Minimal RAGState dict for node tests.

    When ``query`` is overridden the default HumanMessage is updated to match,
    so that ``_classify_intent`` (which prefers messages[-1]) sees the right text.
    """
    from langchain_core.messages import HumanMessage
    from schemas.retrieval import Intent

    default_query = overrides.get("query", "Hvordan nulstiller jeg min adgangskode?")
    state: dict = {
        "messages": [HumanMessage(content=default_query)],
        "query": default_query,
        "standalone_query": "",
        "intent": Intent.ARTIST_INFO,
        "query_variants": [],
        "retrieved_chunks": [],
        "graded_chunks": [],
        "response": "",
        "trace_id": "test-trace",
        "confident": True,
        "retry_count": 0,
    }
    state.update(overrides)
    return state


def _mock_llm_response(text: str):
    """Build a fake ChatAnthropic.ainvoke response (AIMessage)."""
    from langchain_core.messages import AIMessage

    return AIMessage(content=text)


# ---------------------------------------------------------------------------
# classify_intent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_intent_procedural_query():
    """Procedural Danish query maps to Intent.ARTIST_INFO via bridge INTENT_MAP.

    Uses multiple unambiguous procedural keywords so the intent scores above factual.
    "vejledning" + "trin" + "konfigurere" → procedural score 3, factual score 0.
    """
    from orchestration.graph import _classify_intent
    from schemas.retrieval import Intent

    query = "Trin for trin vejledning til at konfigurere integration"
    state = _base_state(query=query)
    result = await _classify_intent(state)

    assert result["intent"] == Intent.ARTIST_INFO
    assert result["query"] == query


@pytest.mark.asyncio
async def test_classify_intent_troubleshooting_query():
    """Error/problem query maps to Intent.ARTIST_INFO via bridge INTENT_MAP."""
    from orchestration.graph import _classify_intent
    from schemas.retrieval import Intent

    state = _base_state(query="Der er en fejl i mit abonnement, det virker ikke")
    result = await _classify_intent(state)

    assert result["intent"] == Intent.ARTIST_INFO


@pytest.mark.asyncio
async def test_classify_intent_extracts_query_from_messages():
    """classify_intent pulls query from last HumanMessage when state.query is empty."""
    from langchain_core.messages import HumanMessage
    from orchestration.graph import _classify_intent

    state = _base_state(
        query="",
        messages=[HumanMessage(content="Hvad er prisen på enterprise-planen?")],
    )
    result = await _classify_intent(state)

    assert result["query"] == "Hvad er prisen på enterprise-planen?"


@pytest.mark.asyncio
async def test_classify_intent_returns_variants():
    """Domain term expansion produces query_variants list."""
    from orchestration.graph import _classify_intent

    state = _base_state(query="Hvordan eksporterer jeg faktura data via api?")
    result = await _classify_intent(state)

    # Expanded query differs due to TERM_EXPANSIONS → variants should be non-empty
    assert isinstance(result["query_variants"], list)
    assert len(result["query_variants"]) <= 3


# ---------------------------------------------------------------------------
# rewrite_query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rewrite_query_single_turn_skips_llm():
    """Single-turn conversation returns original query without LLM call."""
    from orchestration.graph import _rewrite_query

    mock_llm = AsyncMock()
    state = _base_state()  # only one message
    result = await _rewrite_query(state, mock_llm)

    assert result["standalone_query"] == state["query"]
    mock_llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_rewrite_query_multi_turn_calls_haiku():
    """Multi-turn conversation calls Haiku to rewrite query."""
    from langchain_core.messages import AIMessage, HumanMessage
    from orchestration.graph import _rewrite_query

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=_mock_llm_response("Hvordan nulstiller jeg min adgangskode?")
    )

    state = _base_state(
        messages=[
            HumanMessage(content="Hej"),
            AIMessage(content="Hej! Hvordan kan jeg hjælpe?"),
            HumanMessage(content="Kan du hjælpe mig med det?"),
        ],
        query="Kan du hjælpe mig med det?",
    )
    result = await _rewrite_query(state, mock_llm)

    mock_llm.ainvoke.assert_called_once()
    assert result["standalone_query"] == "Hvordan nulstiller jeg min adgangskode?"


# ---------------------------------------------------------------------------
# retrieve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_calls_hybrid_search():
    """retrieve calls hybrid_search and returns deduplicated results."""
    from orchestration.graph import _retrieve

    mock_client = AsyncMock()
    mock_client.hybrid_search = AsyncMock(
        return_value=[_make_retrieval_result("c1"), _make_retrieval_result("c2")]
    )
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1] * 1024

    state = _base_state(standalone_query="Nulstil adgangskode", query_variants=[])
    result = await _retrieve(state, mock_client, mock_embedder)

    assert len(result["retrieved_chunks"]) == 2
    mock_client.hybrid_search.assert_called_once()


@pytest.mark.asyncio
async def test_retrieve_deduplicates_across_variants():
    """Same chunk from multiple variant queries is deduplicated."""
    from orchestration.graph import _retrieve

    mock_client = AsyncMock()
    # Same chunk c1 returned for both queries
    mock_client.hybrid_search = AsyncMock(return_value=[_make_retrieval_result("c1")])
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1] * 1024

    state = _base_state(
        standalone_query="Reset password",
        query_variants=["Nulstil adgangskode"],
    )
    result = await _retrieve(state, mock_client, mock_embedder)

    chunk_ids = [r.chunk.id for r in result["retrieved_chunks"]]
    assert chunk_ids.count("c1") == 1  # deduplicated
    assert mock_client.hybrid_search.call_count == 2  # called for both queries


# ---------------------------------------------------------------------------
# grade_docs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grade_docs_relevant_chunk_sets_confident():
    """Chunks with high relevance score → confident=True."""
    from orchestration.graph import _grade_docs

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=_mock_llm_response("0.9"))

    state = _base_state(retrieved_chunks=[_make_retrieval_result("c1")])
    result = await _grade_docs(state, mock_llm)

    assert result["confident"] is True
    assert result["graded_chunks"][0].relevant is True
    assert result["retry_count"] == 1


@pytest.mark.asyncio
async def test_grade_docs_irrelevant_chunks_sets_not_confident():
    """All chunks below threshold → confident=False."""
    from orchestration.graph import _grade_docs

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=_mock_llm_response("0.1"))

    state = _base_state(
        retrieved_chunks=[
            _make_retrieval_result("c1"),
            _make_retrieval_result("c2"),
        ]
    )
    result = await _grade_docs(state, mock_llm)

    assert result["confident"] is False
    assert all(not g.relevant for g in result["graded_chunks"])


@pytest.mark.asyncio
async def test_grade_docs_increments_retry_count():
    """retry_count is incremented by 1 on each call."""
    from orchestration.graph import _grade_docs

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=_mock_llm_response("0.3"))

    state = _base_state(retry_count=0, retrieved_chunks=[_make_retrieval_result("c1")])
    result = await _grade_docs(state, mock_llm)

    assert result["retry_count"] == 1


@pytest.mark.asyncio
async def test_grade_docs_handles_non_numeric_llm_response():
    """Non-numeric LLM response defaults score to 0.5 (relevant=True)."""
    from orchestration.graph import _grade_docs

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=_mock_llm_response("ja"))

    state = _base_state(retrieved_chunks=[_make_retrieval_result("c1")])
    result = await _grade_docs(state, mock_llm)

    assert result["graded_chunks"][0].score == 0.5
    assert result["graded_chunks"][0].relevant is True  # 0.5 >= 0.5


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_with_graded_chunks_builds_context():
    """generate includes chunk context in user prompt for non-direct intents."""
    from orchestration.graph import _generate
    from schemas.retrieval import Intent

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=_mock_llm_response("Her er svaret."))

    state = _base_state(
        intent=Intent.ARTIST_INFO,
        standalone_query="Hvordan nulstiller jeg adgangskode?",
        graded_chunks=[_make_graded_chunk("c1", relevant=True)],
    )
    result = await _generate(state, mock_llm)

    assert result["response"] == "Her er svaret."
    # call_llm passes [SystemMessage, HumanMessage] to llm.ainvoke
    lc_messages = mock_llm.ainvoke.call_args[0][0]
    assert "Context:" in lc_messages[1].content


@pytest.mark.asyncio
async def test_generate_direct_intent_no_context():
    """chit_chat / out_of_scope routes use query directly without doc context."""
    from orchestration.graph import _generate
    from schemas.retrieval import Intent

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=_mock_llm_response("Ingen problem!"))

    state = _base_state(
        intent=Intent.CHIT_CHAT,
        query="Hej!",
        standalone_query="Hej!",
        graded_chunks=[],
    )
    await _generate(state, mock_llm)

    lc_messages = mock_llm.ainvoke.call_args[0][0]
    assert "Context:" not in lc_messages[1].content


# ---------------------------------------------------------------------------
# confidence_gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confidence_gate_passes_through_when_confident():
    """Returns empty dict (no override) when confident=True."""
    from orchestration.graph import _confidence_gate

    state = _base_state(
        confident=True,
        graded_chunks=[_make_graded_chunk("c1")],
        response="Svar her",
    )
    result = await _confidence_gate(state)

    assert result == {}


@pytest.mark.asyncio
async def test_confidence_gate_passes_through_for_direct_intent():
    """chit_chat / out_of_scope: gate never fires even though graded_chunks is empty."""
    from orchestration.graph import _confidence_gate
    from schemas.retrieval import Intent

    for intent in (Intent.CHIT_CHAT, Intent.OUT_OF_SCOPE):
        state = _base_state(
            intent=intent,
            confident=True,
            graded_chunks=[],  # direct path — retrieval never ran
            response="Hej! Jeg kan hjælpe.",
        )
        result = await _confidence_gate(state)
        assert result == {}, f"confidence_gate should pass through for {intent}"


@pytest.mark.asyncio
async def test_confidence_gate_sets_no_answer_when_not_confident():
    """Overrides response with NO_ANSWER_MESSAGE when confident=False."""
    from orchestration.graph import NO_ANSWER_MESSAGE, _confidence_gate

    state = _base_state(
        confident=False,
        graded_chunks=[_make_graded_chunk("c1", relevant=False)],
        response="Noget forkert",
    )
    result = await _confidence_gate(state)

    assert result["response"] == NO_ANSWER_MESSAGE


@pytest.mark.asyncio
async def test_confidence_gate_sets_no_answer_when_no_chunks():
    """Overrides response when graded_chunks is empty (e.g. no docs retrieved)."""
    from orchestration.graph import NO_ANSWER_MESSAGE, _confidence_gate

    state = _base_state(confident=True, graded_chunks=[], response="Svar")
    result = await _confidence_gate(state)

    assert result["response"] == NO_ANSWER_MESSAGE


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------


def test_route_intent_returns_retrieval_for_artist_info():
    from orchestration.graph import route_intent
    from schemas.retrieval import Intent

    state = _base_state(intent=Intent.ARTIST_INFO)
    assert route_intent(state) == "retrieval"


def test_route_intent_returns_direct_for_chit_chat():
    from orchestration.graph import route_intent
    from schemas.retrieval import Intent

    state = _base_state(intent=Intent.CHIT_CHAT)
    assert route_intent(state) == "direct"


def test_route_intent_returns_direct_for_out_of_scope():
    from orchestration.graph import route_intent
    from schemas.retrieval import Intent

    state = _base_state(intent=Intent.OUT_OF_SCOPE)
    assert route_intent(state) == "direct"


def test_check_sufficient_returns_sufficient_when_confident():
    from orchestration.graph import check_sufficient

    state = _base_state(confident=True, retry_count=0)
    assert check_sufficient(state) == "sufficient"


def test_check_sufficient_returns_insufficient_when_not_confident():
    from orchestration.graph import check_sufficient

    state = _base_state(confident=False, retry_count=0)
    assert check_sufficient(state) == "insufficient"


def test_check_sufficient_allows_one_retry():
    """retry_count=1 (after first grade_docs run) still allows 1 retry."""
    from orchestration.graph import check_sufficient

    state = _base_state(confident=False, retry_count=1)
    assert check_sufficient(state) == "insufficient"


def test_check_sufficient_returns_sufficient_at_retry_limit():
    """Prevents infinite loop: returns 'sufficient' when retry_count >= 2."""
    from orchestration.graph import check_sufficient

    state = _base_state(confident=False, retry_count=2)
    assert check_sufficient(state) == "sufficient"


def test_check_sufficient_returns_sufficient_when_retry_exceeded():
    """retry_count > 2 also returns 'sufficient'."""
    from orchestration.graph import check_sufficient

    state = _base_state(confident=False, retry_count=3)
    assert check_sufficient(state) == "sufficient"
