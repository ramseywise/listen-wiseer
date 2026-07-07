"""Agentic web search — query decomposition, confidence gating, cited sources.

Replaces the old single-shot Tavily call. Complex/multi-part questions are
decomposed (agent.intent.decompose_query) into sub-queries and searched in
parallel; when more than one sub-query fires, one LLM call synthesizes a single
answer with citations. Confidence comes from what Tavily actually returned
(direct answer > raw results > nothing) — modeled on playground's lg_agent CRAG
confidence gate, adapted for API search since there's no owned corpus to score
against. See .claude/docs/plans/phase8-rag-rightsize-agentic-search.md.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

from agent.intent import decompose_query, score_complexity
from utils.logging import get_logger

log = get_logger(__name__)

Confidence = Literal["high", "medium", "low"]
_CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}
_MAX_SUB_QUERIES = 3


def _tavily_client():
    from utils.config import settings

    if not settings.tavily_api_key:
        return None
    from tavily import TavilyClient

    return TavilyClient(api_key=settings.tavily_api_key)


def _tavily_search(client, query: str) -> dict:
    """One Tavily call. Returns {"text", "sources", "confidence"}."""
    response = client.search(
        query=query,
        search_depth="advanced",
        max_results=4,
        include_answer=True,
    )
    answer = response.get("answer")
    results = response.get("results", [])
    sources = [{"title": r.get("title", ""), "url": r["url"]} for r in results if r.get("url")]

    if answer:
        return {"text": answer, "sources": sources, "confidence": "high"}
    if results:
        text = "\n\n".join(r["content"][:600] for r in results[:3])
        return {"text": text, "sources": sources, "confidence": "medium"}
    return {"text": "", "sources": [], "confidence": "low"}


def _wikipedia_fallback(query: str) -> dict:
    """Last-resort fallback when Tavily is unavailable or found nothing."""
    try:
        import wikipedia

        try:
            page = wikipedia.page(query, auto_suggest=True)
        except wikipedia.exceptions.DisambiguationError as exc:
            page = wikipedia.page(exc.options[0], auto_suggest=False)
    except Exception as exc:
        log.debug("web_search.wikipedia.skip", query=query, reason=str(exc))
        return {"text": "", "sources": [], "confidence": "low"}

    return {
        "text": page.summary[:1500],
        "sources": [{"title": page.title, "url": page.url}],
        "confidence": "medium",
    }


def _dedupe_sources(hits: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for hit in hits:
        for source in hit["sources"]:
            if source["url"] not in seen:
                seen.add(source["url"])
                out.append(source)
    return out


def _synthesize(subject: str, hits: list[dict]) -> str:
    """Merge multiple sub-query results into one answer with inline citations."""
    from agent.graph_nodes import _llm  # shared Haiku instance

    passages = "\n\n".join(f"[{i + 1}] {hit['text']}" for i, hit in enumerate(hits))
    prompt = (
        f"Synthesize a concise, accurate answer about '{subject}' from these search "
        f"results. Cite passage numbers like [1] inline where relevant.\n\n{passages}"
    )
    response = _llm.invoke([HumanMessage(content=prompt)])
    return str(response.content).strip()


def _agentic_search(subject: str, query: str, wiki_query: str | None = None) -> tuple[str, dict]:
    """Plan -> fan out -> synthesize -> confidence-gate.

    Returns (text_for_llm, {"sources": [...], "confidence": tier}) — used with
    response_format="content_and_artifact" so citations reach format_response
    without cluttering the LLM's view of the tool output.
    """
    client = _tavily_client()
    if client is None:
        hits = [_wikipedia_fallback(wiki_query or query)]
    else:
        sub_queries = decompose_query(query)[:_MAX_SUB_QUERIES]
        complexity = score_complexity(query, entities={}, sub_queries=sub_queries)
        queries = sub_queries if complexity != "simple" and len(sub_queries) > 1 else [query]

        with ThreadPoolExecutor(max_workers=len(queries)) as pool:
            hits = list(pool.map(lambda q: _tavily_search(client, q), queries))

        if all(not hit["text"] for hit in hits):
            hits.append(_wikipedia_fallback(wiki_query or query))

    non_empty = [hit for hit in hits if hit["text"]]
    sources = _dedupe_sources(hits)

    if not non_empty:
        return f"I couldn't find reliable information on '{subject}'.", {
            "sources": [],
            "confidence": "low",
        }

    text = non_empty[0]["text"] if len(non_empty) == 1 else _synthesize(subject, non_empty)
    confidence = max(
        (hit["confidence"] for hit in non_empty), key=lambda tier: _CONFIDENCE_RANK[tier]
    )
    return text, {"sources": sources, "confidence": confidence}


def _get_artist_context(subject: str) -> tuple[str, dict]:
    query = f"{subject} musician biography history influences"
    return _agentic_search(subject, query, wiki_query=subject)


get_artist_context_tool = StructuredTool.from_function(
    _get_artist_context,
    name="get_artist_context",
    description=(
        "Retrieve biographical info and interesting facts about a musician or band. "
        "Use when the user asks who an artist is, what they're known for, "
        "their history, influences, or style."
    ),
    response_format="content_and_artifact",
)


def _get_genre_context(genre: str) -> tuple[str, dict]:
    query = (
        f"{genre} music genre: origins, history, defining characteristics, "
        f"key artists, related subgenres"
    )
    return _agentic_search(genre, query, wiki_query=f"{genre} music")


get_genre_context_tool = StructuredTool.from_function(
    _get_genre_context,
    name="get_genre_context",
    description=(
        "Retrieve structured information about a music genre: origins, history, "
        "defining characteristics, key artists, and related subgenres. "
        "Use when the user asks what a genre is, its roots, or how it differs from related genres."
    ),
    response_format="content_and_artifact",
)
