"""On-demand content fetchers for the RAG lazy-ingestion pipeline.

Wikipedia is the primary source. Tavily is an optional web-search fallback
(requires ``tavily-python`` installed + ``TAVILY_API_KEY`` set in env).
"""

from __future__ import annotations

import wikipedia

from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)


def fetch_wikipedia(subject: str, language: str = "en") -> str | None:
    """Fetch the Wikipedia summary + content for *subject*.

    Handles disambiguation by trying the first suggested option.
    Returns ``None`` when no page is found.
    """
    wikipedia.set_lang(language)
    try:
        page = wikipedia.page(subject, auto_suggest=True)
        log.info(
            "fetchers.wikipedia.ok",
            subject=subject,
            url=page.url,
            length=len(page.content),
        )
        return page.content
    except wikipedia.exceptions.DisambiguationError as exc:
        if exc.options:
            first = exc.options[0]
            log.info("fetchers.wikipedia.disambiguate", subject=subject, first=first)
            try:
                page = wikipedia.page(first, auto_suggest=False)
                return page.content
            except (
                wikipedia.exceptions.PageError,
                wikipedia.exceptions.WikipediaException,
            ):
                log.warning("fetchers.wikipedia.disambiguate_failed", first=first)
                return None
        return None
    except wikipedia.exceptions.PageError:
        log.info("fetchers.wikipedia.not_found", subject=subject)
        return None
    except wikipedia.exceptions.WikipediaException as exc:
        log.error("fetchers.wikipedia.error", subject=subject, error=str(exc))
        return None


def fetch_tavily(subject: str) -> str | None:
    """Search for *subject* via Tavily web search API.

    Returns concatenated search result content, or ``None`` if Tavily is not
    installed, no API key is set, or the search fails.
    """
    api_key = settings.tavily_api_key
    if not api_key:
        log.debug("fetchers.tavily.no_api_key")
        return None

    try:
        from tavily import TavilyClient  # lazy import — not a hard dependency
    except ImportError:
        log.debug("fetchers.tavily.not_installed")
        return None

    try:
        client = TavilyClient(api_key=api_key)
        results = client.search(
            query=f"{subject} musician artist biography",
            max_results=3,
            search_depth="basic",
        )
        contents = [r["content"] for r in results.get("results", []) if r.get("content")]
        if not contents:
            log.info("fetchers.tavily.empty", subject=subject)
            return None

        combined = "\n\n".join(contents)
        log.info("fetchers.tavily.ok", subject=subject, n_results=len(contents))
        return combined
    except (ConnectionError, TimeoutError, ValueError) as exc:
        log.error("fetchers.tavily.error", subject=subject, error=str(exc))
        return None
