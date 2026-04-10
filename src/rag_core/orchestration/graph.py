"""LangGraph RAG pipeline for the music assistant.

Graph topology:
    START → analyze
    analyze ──[direct]──────────────────────────────────► generate
    analyze ──[snippet]──► snippet_retrieve ─────────────► generate
    analyze ──[retrieve]─► retrieve → rerank → gate ──────► generate
                                               │
                                  CRAG retry ◄─┘ (gate → retrieve, max retries)
    generate → END

Nodes are thin async closures that delegate to Subgraph helper objects,
keeping build_graph readable and each component independently testable.
"""

from __future__ import annotations

from generation.generator import SONNET_MODEL, build_prompt, call_llm, extract_citations
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from retrieval.chroma_client import ChromaRetriever
from retrieval.embedder import MiniLMEmbedder
from retrieval.reranker import CrossEncoderReranker
from schemas.conversation import RAGState
from schemas.retrieval import GradedChunk, Intent, RankedChunk, RetrievalResult

from orchestration.query_understanding import QueryAnalyzer
from orchestration.router import QueryRouter
from utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HAIKU_MODEL = "claude-haiku-4-5-20251001"

NO_ANSWER_MESSAGE = (
    "I'm sorry, I couldn't find enough information to answer your question. "
    "Try asking about a specific artist, band, or music genre."
)

_DIRECT_INTENTS = {Intent.CHIT_CHAT, Intent.OUT_OF_SCOPE}
_CONFIDENCE_THRESHOLD = 0.35
_MAX_RETRIES = 2

_INTENT_MAP: dict[str, Intent] = {
    "artist_info": Intent.ARTIST_INFO,
    "genre_info": Intent.GENRE_INFO,
    "recommendation": Intent.RECOMMENDATION,
    "history": Intent.HISTORY,
    "chit_chat": Intent.CHIT_CHAT,
    "out_of_scope": Intent.OUT_OF_SCOPE,
}

# ---------------------------------------------------------------------------
# Module-level singletons (created once per process)
# ---------------------------------------------------------------------------

_analyzer = QueryAnalyzer()
_router = QueryRouter(_analyzer)

# ---------------------------------------------------------------------------
# Routing helpers (conditional-edge functions)
# ---------------------------------------------------------------------------


def route_after_analyze(state: RAGState) -> str:
    """Three-way route: direct | snippet | retrieve."""
    intent = state.get("intent")
    if intent in _DIRECT_INTENTS:
        return "direct"
    if state.get("retrieval_mode") == "snippet":
        return "snippet"
    return "retrieve"


def route_after_gate(state: RAGState) -> str:
    """CRAG gate: proceed to generate or loop back to retrieve."""
    if state.get("fallback_requested") and state.get("retry_count", 0) < _MAX_RETRIES:
        return "retry"
    return "generate"


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


async def _analyze(state: RAGState) -> dict:
    """Rule-based intent classification + retrieval mode selection."""
    query: str = state.get("query", "")
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            query = str(msg.content)
            break

    decision = _router.route(query)
    analysis = decision.query_analysis

    intent = _INTENT_MAP.get(analysis.intent if analysis else "artist_info", Intent.ARTIST_INFO)

    variants: list[str] = []
    if analysis:
        if analysis.expanded_query and analysis.expanded_query != query:
            variants.append(analysis.expanded_query)
        for sq in analysis.sub_queries:
            if sq != query and sq not in variants:
                variants.append(sq)

    log.info(
        "graph.analyze",
        intent=str(intent),
        strategy=str(decision.strategy),
        retrieval_mode=decision.retrieval_mode,
        n_variants=len(variants),
    )
    return {
        "query": query,
        "intent": intent,
        "retrieval_mode": decision.retrieval_mode,
        "query_variants": variants[:3],
        "retry_count": 0,
        "fallback_requested": False,
    }


async def _snippet_retrieve(
    state: RAGState,
    snippet_db: object | None,
) -> dict:
    """Fast FTS retrieval via SnippetDB — bypasses embedding and reranker.

    Falls through to empty graded_chunks if snippet_db is not configured,
    which will trigger the confidence gate to fall back to the dense path.
    """
    if snippet_db is None:
        log.info("graph.snippet_retrieve.no_db")
        return {
            "retrieved_chunks": [],
            "graded_chunks": [],
            "reranked_chunks": [],
            "confidence_score": 0.0,
        }

    query: str = state.get("query", "")
    rows = snippet_db.search_snippets(query, k=5)  # type: ignore[attr-defined]

    # Convert snippet rows → GradedChunk (relevant=True for all FTS hits)
    from schemas.chunks import Chunk, ChunkMetadata

    graded: list[GradedChunk] = []
    for row in rows:
        chunk = Chunk(
            id=row["id"],
            text=row["text"],
            metadata=ChunkMetadata(
                url=row.get("source", ""),
                title=row.get("title", ""),
                section="snippet",
                doc_id=row["doc_id"],
            ),
        )
        graded.append(GradedChunk(chunk=chunk, score=row.get("score", 1.0), relevant=True))

    # Promote to RankedChunk (skip reranker for snippet path)
    ranked = [
        RankedChunk(chunk=gc.chunk, relevance_score=gc.score, rank=i + 1)
        for i, gc in enumerate(graded)
    ]
    confidence = max((gc.score for gc in graded), default=0.0)

    log.info("graph.snippet_retrieve.done", n_snippets=len(graded))
    return {
        "retrieved_chunks": [],
        "graded_chunks": graded,
        "reranked_chunks": ranked,
        "confidence_score": confidence,
        "confident": bool(graded),
        "fallback_requested": not bool(graded),
    }


async def _retrieve(
    state: RAGState,
    client: ChromaRetriever,
    embedder: MiniLMEmbedder,
) -> dict:
    """Hybrid search for query + variants; deduplicate by chunk.id."""
    query: str = state.get("query", "")
    variants: list[str] = state.get("query_variants", [])

    queries = [query] + [v for v in variants if v != query]
    seen_ids: set[str] = set()
    all_results: list[RetrievalResult] = []

    for q in queries:
        vector = embedder.embed_query(q)
        results = await client.search(
            query_text=q,
            query_vector=vector,
            k=8,
        )
        for r in results:
            if r.chunk.id not in seen_ids:
                seen_ids.add(r.chunk.id)
                all_results.append(r)

    all_results.sort(key=lambda r: r.score, reverse=True)
    top = all_results[:10]

    # Grade by retrieval score threshold
    graded = [GradedChunk(chunk=r.chunk, score=r.score, relevant=r.score >= 0.1) for r in top]

    log.info("graph.retrieve", n_results=len(top))
    return {"retrieved_chunks": top, "graded_chunks": graded}


async def _rerank(
    state: RAGState,
    reranker: CrossEncoderReranker,
    top_k: int = 5,
) -> dict:
    """Cross-encoder reranking of retrieved chunks."""
    query: str = state.get("query", "")
    graded: list[GradedChunk] = state.get("graded_chunks", [])

    candidates = [gc for gc in graded if gc.relevant] or graded
    ranked = await reranker.rerank(query, candidates, top_k=top_k)
    confidence = max((r.relevance_score for r in ranked), default=0.0)

    log.info("graph.rerank", n_ranked=len(ranked), confidence=confidence)
    return {"reranked_chunks": ranked, "confidence_score": confidence}


async def _gate(state: RAGState) -> dict:
    """Pre-generate confidence gate — triggers CRAG retry if score is too low."""
    score: float = state.get("confidence_score", 0.0)
    retry_count: int = state.get("retry_count", 0) + 1
    fallback = score < _CONFIDENCE_THRESHOLD

    log.info(
        "graph.gate",
        confidence_score=score,
        retry_count=retry_count,
        fallback_requested=fallback,
    )
    return {
        "retry_count": retry_count,
        "confident": not fallback,
        "fallback_requested": fallback,
    }


async def _generate(state: RAGState, sonnet: ChatAnthropic) -> dict:
    """Generate answer using Claude Sonnet with intent-specific system prompt."""
    intent: Intent = state.get("intent", Intent.ARTIST_INFO)
    reranked: list[RankedChunk] = state.get("reranked_chunks", [])

    # If no ranked chunks (direct intent or snippet with nothing), pass empty list
    system_prompt, messages = build_prompt(state, reranked)
    answer = await call_llm(sonnet, system_prompt, messages)

    # Replace with fallback message if not confident and retrieval was attempted
    if not state.get("confident", True) and intent not in _DIRECT_INTENTS and not reranked:
        answer = NO_ANSWER_MESSAGE

    citations = extract_citations(reranked)

    log.info("graph.generate", intent=str(intent), response_len=len(answer))
    return {"response": answer, "citations": citations}


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------


def build_graph(
    client: ChromaRetriever,
    embedder: MiniLMEmbedder,
    reranker: CrossEncoderReranker | None = None,
    snippet_db: object | None = None,
    anthropic_api_key: str | None = None,
) -> StateGraph:
    """Build and return the compiled RAG StateGraph (without checkpointer).

    Args:
        client:           ChromaRetriever instance.
        embedder:         MiniLMEmbedder instance.
        reranker:         CrossEncoderReranker; instantiated here if None.
        snippet_db:       Optional SnippetDB for fast factual queries.
        anthropic_api_key: Passed to ChatAnthropic; uses env var if None.
    """
    _reranker = reranker or CrossEncoderReranker()
    sonnet = ChatAnthropic(model=SONNET_MODEL, max_tokens=1024, api_key=anthropic_api_key)  # type: ignore[arg-type]

    async def analyze_node(state: RAGState) -> dict:
        return await _analyze(state)

    async def snippet_retrieve_node(state: RAGState) -> dict:
        return await _snippet_retrieve(state, snippet_db)

    async def retrieve_node(state: RAGState) -> dict:
        return await _retrieve(state, client, embedder)

    async def rerank_node(state: RAGState) -> dict:
        return await _rerank(state, _reranker)

    async def gate_node(state: RAGState) -> dict:
        return await _gate(state)

    async def generate_node(state: RAGState) -> dict:
        return await _generate(state, sonnet)

    graph = StateGraph(RAGState)
    graph.add_node("analyze", analyze_node)
    graph.add_node("snippet_retrieve", snippet_retrieve_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("rerank", rerank_node)
    graph.add_node("gate", gate_node)
    graph.add_node("generate", generate_node)

    graph.set_entry_point("analyze")
    graph.add_conditional_edges(
        "analyze",
        route_after_analyze,
        {
            "direct": "generate",
            "snippet": "snippet_retrieve",
            "retrieve": "retrieve",
        },
    )
    graph.add_edge("snippet_retrieve", "generate")
    graph.add_edge("retrieve", "rerank")
    graph.add_edge("rerank", "gate")
    graph.add_conditional_edges(
        "gate",
        route_after_gate,
        {
            "generate": "generate",
            "retry": "retrieve",
        },
    )
    graph.add_edge("generate", END)

    return graph


def create_rag_app(
    client: ChromaRetriever,
    embedder: MiniLMEmbedder,
    reranker: CrossEncoderReranker | None = None,
    snippet_db: object | None = None,
    anthropic_api_key: str | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> object:
    """Build and compile the RAG app with a checkpointer.

    Usage:
        config = {"configurable": {"thread_id": session_id}}
        result = await app.ainvoke({"messages": [HumanMessage(content=query)]}, config=config)
    """
    graph = build_graph(client, embedder, reranker, snippet_db, anthropic_api_key)
    return graph.compile(checkpointer=checkpointer or MemorySaver())
