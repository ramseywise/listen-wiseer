"""LangGraph query pipeline for RAG music assistant.

Graph nodes (each returns a partial state update dict):
    classify_intent  → rewrite_query → retrieve → grade_docs ─┐
                   ↘ generate (direct: chit_chat/out_of_scope)  │
                                              └── generate → confidence_gate → END
                              (CRAG retry: grade_docs → rewrite_query, max 1 retry)
"""

from __future__ import annotations

from generation.generator import SONNET_MODEL, build_prompt, call_llm
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from retrieval.duckdb_client import DuckDBVectorClient
from retrieval.embedder import MultilingualEmbedder
from schemas.conversation import RAGState
from schemas.retrieval import GradedChunk, Intent, RetrievalResult

from orchestration.query_understanding import QueryAnalyzer
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

# Maps QueryAnalyzer intent strings → Intent enum
# Bridge mapping until Phase 5b replaces QueryAnalyzer with music-domain classifier
INTENT_MAP: dict[str, Intent] = {
    "factual": Intent.ARTIST_INFO,
    "procedural": Intent.ARTIST_INFO,
    "exploratory": Intent.GENRE_INFO,
    "troubleshooting": Intent.ARTIST_INFO,
}

_DIRECT_INTENTS = {Intent.CHIT_CHAT, Intent.OUT_OF_SCOPE}

# ---------------------------------------------------------------------------
# Routing helpers (used as conditional-edge functions)
# ---------------------------------------------------------------------------

_analyzer = QueryAnalyzer()


def route_intent(state: RAGState) -> str:
    """Return edge label based on intent."""
    if state.get("intent") in _DIRECT_INTENTS:
        return "direct"
    return "retrieval"


def check_sufficient(state: RAGState) -> str:
    """Return 'sufficient' when docs pass grading or retry limit reached.

    grade_docs increments retry_count before this is called, so the first
    run ends with retry_count=1. Allowing 1 actual retry means the loop
    fires when retry_count < 2 (i.e. the second grade_docs call, at count=2,
    is the hard stop).
    """
    if state.get("confident", True) or state.get("retry_count", 0) >= 2:
        return "sufficient"
    return "insufficient"


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


async def _classify_intent(state: RAGState) -> dict:
    """Classify intent and expand query using QueryAnalyzer (no LLM call)."""
    # Prefer last HumanMessage; fall back to state["query"]
    query: str = state.get("query", "")
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            query = str(msg.content)
            break

    analysis = _analyzer.analyze(query)
    intent = INTENT_MAP.get(analysis.intent, Intent.ARTIST_INFO)

    # Collect up to 3 query variants from expansion + sub-queries
    variants: list[str] = []
    if analysis.expanded_query and analysis.expanded_query != query:
        variants.append(analysis.expanded_query)
    for sq in analysis.sub_queries:
        if sq != query and sq not in variants:
            variants.append(sq)

    log.info(
        "graph.classify_intent",
        intent=str(intent),
        complexity=analysis.complexity,
        n_variants=len(variants),
    )
    return {
        "query": query,
        "intent": intent,
        "query_variants": variants[:3],
    }


async def _rewrite_query(state: RAGState, haiku: ChatAnthropic) -> dict:
    """Rewrite the query as a standalone question resolving coreferences."""
    query: str = state.get("query", "")
    messages = state.get("messages", [])

    # Single-turn: no history to resolve
    if len(messages) <= 1:
        return {"standalone_query": query}

    recent = messages[-5:]
    history_lines: list[str] = []
    for msg in recent[:-1]:
        role = "User" if isinstance(msg, HumanMessage) else "Assistant"
        history_lines.append(f"{role}: {msg.content}")
    history = "\n".join(history_lines)

    prompt = (
        f"Based on the conversation history, rewrite the following question "
        f"as a standalone question without pronouns or references:\n\n"
        f"History:\n{history}\n\n"
        f"Question: {query}\n\n"
        f"Standalone question (question only, no explanation):"
    )
    response: AIMessage = await haiku.ainvoke([HumanMessage(content=prompt)])
    standalone = str(response.content).strip()
    log.info("graph.rewrite_query", original=query, standalone=standalone)
    return {"standalone_query": standalone}


async def _retrieve(
    state: RAGState,
    client: DuckDBVectorClient,
    embedder: MultilingualEmbedder,
) -> dict:
    """Hybrid search for standalone_query + each variant; deduplicate by chunk.id."""
    standalone: str = state.get("standalone_query") or state.get("query", "")
    variants: list[str] = state.get("query_variants", [])

    queries = [standalone] + [v for v in variants if v != standalone]
    seen_ids: set[str] = set()
    all_results: list[RetrievalResult] = []

    for q in queries:
        vector = embedder.embed_query(q)
        results = await client.hybrid_search(
            query_text=q,
            query_vector=vector,
            k=5,
        )
        for r in results:
            if r.chunk.id not in seen_ids:
                seen_ids.add(r.chunk.id)
                all_results.append(r)

    all_results.sort(key=lambda r: r.score, reverse=True)
    top_results = all_results[:5]

    log.info("graph.retrieve", n_results=len(top_results))
    return {"retrieved_chunks": top_results}


async def _grade_docs(state: RAGState, haiku: ChatAnthropic) -> dict:
    """Grade each retrieved chunk for relevance (CRAG step)."""
    query: str = state.get("standalone_query") or state.get("query", "")
    chunks: list[RetrievalResult] = state.get("retrieved_chunks", [])
    graded: list[GradedChunk] = []

    for result in chunks:
        prompt = (
            f"Is the following text relevant to answering the question? "
            f"Reply ONLY with a number between 0 and 1 (e.g. 0.8).\n\n"
            f"Question: {query}\n\n"
            f"Text: {result.chunk.text[:500]}\n\n"
            f"Relevance (0–1):"
        )
        response: AIMessage = await haiku.ainvoke([HumanMessage(content=prompt)])
        raw = str(response.content).strip()
        try:
            score = max(0.0, min(1.0, float(raw)))
        except ValueError:
            score = 0.5

        graded.append(
            GradedChunk(
                chunk=result.chunk,
                score=score,
                relevant=score >= 0.5,
            )
        )

    confident = any(g.relevant for g in graded)
    retry_count = state.get("retry_count", 0) + 1

    log.info(
        "graph.grade_docs",
        n_graded=len(graded),
        n_relevant=sum(g.relevant for g in graded),
        confident=confident,
        retry_count=retry_count,
    )
    return {
        "graded_chunks": graded,
        "confident": confident,
        "retry_count": retry_count,
    }


async def _generate(state: RAGState, sonnet: ChatAnthropic) -> dict:
    """Generate answer using Claude Sonnet with intent-specific system prompt."""
    intent: Intent = state.get("intent", Intent.ARTIST_INFO)
    graded: list[GradedChunk] = state.get("graded_chunks", [])

    system_prompt, messages = build_prompt(state, graded)
    answer = await call_llm(sonnet, system_prompt, messages)

    log.info("graph.generate", intent=str(intent), response_len=len(answer))
    return {"response": answer}


async def _confidence_gate(state: RAGState) -> dict:
    """Replace response with NO_ANSWER_MESSAGE if not confident after grading.

    Direct-path intents (chit_chat / out_of_scope) skip the retrieval check —
    they never populate graded_chunks, so the empty-chunks guard must not apply.
    """
    intent = state.get("intent", Intent.ARTIST_INFO)
    if intent in _DIRECT_INTENTS:
        return {}
    if not state.get("confident", True) or not state.get("graded_chunks"):
        log.info("graph.confidence_gate", outcome="no_answer")
        return {"response": NO_ANSWER_MESSAGE}
    return {}


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------


def build_graph(
    client: DuckDBVectorClient,
    embedder: MultilingualEmbedder,
    anthropic_api_key: str | None = None,
) -> StateGraph:
    """Build and return the compiled RAG StateGraph (without checkpointer)."""
    haiku = ChatAnthropic(model=HAIKU_MODEL, max_tokens=256, api_key=anthropic_api_key)  # type: ignore[arg-type]
    sonnet = ChatAnthropic(model=SONNET_MODEL, max_tokens=1024, api_key=anthropic_api_key)  # type: ignore[arg-type]

    async def classify_intent_node(state: RAGState) -> dict:
        return await _classify_intent(state)

    async def rewrite_query_node(state: RAGState) -> dict:
        return await _rewrite_query(state, haiku)

    async def retrieve_node(state: RAGState) -> dict:
        return await _retrieve(state, client, embedder)

    async def grade_docs_node(state: RAGState) -> dict:
        return await _grade_docs(state, haiku)

    async def generate_node(state: RAGState) -> dict:
        return await _generate(state, sonnet)

    async def confidence_gate_node(state: RAGState) -> dict:
        return await _confidence_gate(state)

    graph = StateGraph(RAGState)
    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("rewrite_query", rewrite_query_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("grade_docs", grade_docs_node)
    graph.add_node("generate", generate_node)
    graph.add_node("confidence_gate", confidence_gate_node)

    graph.set_entry_point("classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        route_intent,
        {
            "retrieval": "rewrite_query",
            "direct": "generate",
        },
    )
    graph.add_edge("rewrite_query", "retrieve")
    graph.add_edge("retrieve", "grade_docs")
    graph.add_conditional_edges(
        "grade_docs",
        check_sufficient,
        {
            "sufficient": "generate",
            "insufficient": "rewrite_query",
        },
    )
    graph.add_edge("generate", "confidence_gate")
    graph.add_edge("confidence_gate", END)

    return graph


def create_rag_app(
    client: DuckDBVectorClient,
    embedder: MultilingualEmbedder,
    anthropic_api_key: str | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Build the compiled RAG app.

    Pass a RedisSaver (or AsyncRedisSaver) in production; defaults to
    MemorySaver() for local use and unit tests.

    Usage:
        config = {"configurable": {"thread_id": session_id}}
        result = await app.ainvoke({"messages": [HumanMessage(content=query)]}, config=config)
    """
    graph = build_graph(client, embedder, anthropic_api_key)
    return graph.compile(checkpointer=checkpointer or MemorySaver())
