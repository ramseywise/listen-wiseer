from __future__ import annotations

from langchain_core.tools import StructuredTool


def _get_artist_context(subject: str) -> str:
    from utils.config import settings

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
            return answer
        results = response.get("results", [])
        if results:
            return "\n\n".join(r["content"][:600] for r in results[:3])

    try:
        import wikipedia

        page = wikipedia.page(subject, auto_suggest=True)
        return page.summary[:1500]
    except wikipedia.exceptions.DisambiguationError as exc:
        try:
            page = wikipedia.page(exc.options[0], auto_suggest=False)
            return page.summary[:1500]
        except Exception:
            pass
    except Exception:
        pass

    return f"No information found for '{subject}'."


get_artist_context_tool = StructuredTool.from_function(
    _get_artist_context,
    name="get_artist_context",
    description=(
        "Retrieve biographical info and interesting facts about a musician or band. "
        "Use when the user asks who an artist is, what they're known for, "
        "their history, influences, or style. Also works for music genres."
    ),
)
