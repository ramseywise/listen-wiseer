from __future__ import annotations

from langchain_core.tools import StructuredTool

from utils.logging import get_logger

log = get_logger(__name__)


def _query_rag_chunks(subject: str) -> str | None:
    """Return local rag_chunks text for subject, or None if the table is empty."""
    try:
        from etl.db import get_connection

        conn = get_connection(read_only=True)
        rows = conn.execute(
            "SELECT text FROM rag_chunks WHERE subject = ? ORDER BY created_at DESC LIMIT 3",
            [subject],
        ).fetchall()
        conn.close()
        if rows:
            log.debug("web_search.rag_chunks.hit", subject=subject, n=len(rows))
            return "\n\n".join(row[0] for row in rows)
    except Exception as exc:
        log.debug("web_search.rag_chunks.skip", subject=subject, reason=str(exc))
    return None


def _get_artist_context(subject: str) -> str:
    from utils.config import settings

    web_result: str | None = None

    if settings.tavily_api_key:
        from tavily import TavilyClient

        client = TavilyClient(api_key=settings.tavily_api_key)
        response = client.search(
            query=f"{subject} musician biography history influences",
            search_depth="basic",
            max_results=3,
            include_answer=True,
        )
        answer = response.get("answer")
        if answer:
            web_result = answer
        else:
            results = response.get("results", [])
            if results:
                web_result = "\n\n".join(r["content"][:600] for r in results[:3])

    if web_result is None:
        try:
            import wikipedia

            page = wikipedia.page(subject, auto_suggest=True)
            web_result = page.summary[:1500]
        except wikipedia.exceptions.DisambiguationError as exc:
            try:
                page = wikipedia.page(exc.options[0], auto_suggest=False)
                web_result = page.summary[:1500]
            except Exception as inner_exc:
                log.debug("web_search.wikipedia.disambiguation_fallback_failed", subject=subject, reason=str(inner_exc))
        except Exception as exc:
            log.debug("web_search.wikipedia.skip", subject=subject, reason=str(exc))

    if web_result is None:
        return f"No information found for '{subject}'."

    rag_context = _query_rag_chunks(subject)
    if rag_context:
        return f"{web_result}\n\n## Additional context\n{rag_context}"

    return web_result


get_artist_context_tool = StructuredTool.from_function(
    _get_artist_context,
    name="get_artist_context",
    description=(
        "Retrieve biographical info and interesting facts about a musician or band. "
        "Use when the user asks who an artist is, what they're known for, "
        "their history, influences, or style."
    ),
)


def _get_genre_context(genre: str) -> str:
    from utils.config import settings

    web_result: str | None = None

    if settings.tavily_api_key:
        from tavily import TavilyClient

        client = TavilyClient(api_key=settings.tavily_api_key)
        response = client.search(
            query=(
                f"{genre} music genre: origins, history, defining characteristics, "
                f"key artists, related subgenres"
            ),
            search_depth="basic",
            max_results=3,
            include_answer=True,
        )
        answer = response.get("answer")
        if answer:
            web_result = answer
        else:
            results = response.get("results", [])
            if results:
                web_result = "\n\n".join(r["content"][:600] for r in results[:3])

    if web_result is None:
        try:
            import wikipedia

            page = wikipedia.page(f"{genre} music", auto_suggest=True)
            web_result = page.summary[:1500]
        except wikipedia.exceptions.DisambiguationError as exc:
            try:
                page = wikipedia.page(exc.options[0], auto_suggest=False)
                web_result = page.summary[:1500]
            except Exception as inner_exc:
                log.debug(
                    "web_search.wikipedia.genre_fallback_failed",
                    genre=genre,
                    reason=str(inner_exc),
                )
        except Exception as exc:
            log.debug("web_search.wikipedia.genre_skip", genre=genre, reason=str(exc))

    if web_result is None:
        return f"No information found for genre '{genre}'."

    rag_context = _query_rag_chunks(genre)
    if rag_context:
        return f"{web_result}\n\n## Additional context\n{rag_context}"

    return web_result


get_genre_context_tool = StructuredTool.from_function(
    _get_genre_context,
    name="get_genre_context",
    description=(
        "Retrieve structured information about a music genre: origins, history, "
        "defining characteristics, key artists, and related subgenres. "
        "Use when the user asks what a genre is, its roots, or how it differs from related genres."
    ),
)
