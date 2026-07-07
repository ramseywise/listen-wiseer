"""Unit tests for agentic web search — decomposition fan-out, confidence
gating, and citation sources. All Tavily/Wikipedia/LLM calls are mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent.tools.web_search import (
    _agentic_search,
    _dedupe_sources,
    _get_artist_context,
    _get_genre_context,
    _tavily_search,
    _wikipedia_fallback,
)


def _mock_tavily(answer: str | None = None, results: list[dict] | None = None) -> MagicMock:
    client = MagicMock()
    client.search.return_value = {"answer": answer, "results": results or []}
    return client


# =============================================================================
# _tavily_search — confidence tiers
# =============================================================================


class TestTavilySearch:
    def test_direct_answer_is_high_confidence(self) -> None:
        client = _mock_tavily(answer="Bossa nova originated in Rio de Janeiro.")
        result = _tavily_search(client, "bossa nova origins")
        assert result["confidence"] == "high"
        assert "Rio de Janeiro" in result["text"]

    def test_raw_results_only_is_medium_confidence(self) -> None:
        client = _mock_tavily(
            results=[{"title": "Bossa Nova", "url": "https://x.test/a", "content": "..." * 10}]
        )
        result = _tavily_search(client, "bossa nova origins")
        assert result["confidence"] == "medium"
        assert result["sources"] == [{"title": "Bossa Nova", "url": "https://x.test/a"}]

    def test_nothing_found_is_low_confidence(self) -> None:
        client = _mock_tavily()
        result = _tavily_search(client, "some obscure query")
        assert result["confidence"] == "low"
        assert result["text"] == ""
        assert result["sources"] == []

    def test_uses_advanced_search_depth(self) -> None:
        client = _mock_tavily(answer="x")
        _tavily_search(client, "query")
        assert client.search.call_args.kwargs["search_depth"] == "advanced"


# =============================================================================
# _wikipedia_fallback
# =============================================================================


class TestWikipediaFallback:
    def test_success_returns_medium_confidence_with_source(self) -> None:
        fake_page = MagicMock(
            summary="Zouk is a genre from Guadeloupe.",
            url="https://en.wikipedia.org/wiki/Zouk",
            title="Zouk",
        )
        with patch("wikipedia.page", return_value=fake_page):
            result = _wikipedia_fallback("zouk music")
        assert result["confidence"] == "medium"
        assert result["sources"] == [{"title": "Zouk", "url": "https://en.wikipedia.org/wiki/Zouk"}]

    def test_missing_page_returns_low_confidence_empty(self) -> None:
        with patch("wikipedia.page", side_effect=Exception("PageError")):
            result = _wikipedia_fallback("not a real genre xyz")
        assert result == {"text": "", "sources": [], "confidence": "low"}


# =============================================================================
# _dedupe_sources
# =============================================================================


def test_dedupe_sources_drops_repeated_urls() -> None:
    hits = [
        {"sources": [{"title": "A", "url": "https://x.test/1"}]},
        {
            "sources": [
                {"title": "A dup", "url": "https://x.test/1"},
                {"title": "B", "url": "https://x.test/2"},
            ]
        },
    ]
    result = _dedupe_sources(hits)
    assert [s["url"] for s in result] == ["https://x.test/1", "https://x.test/2"]


# =============================================================================
# _agentic_search — planning, fan-out, confidence gate
# =============================================================================


class TestAgenticSearch:
    def test_simple_query_makes_a_single_tavily_call(self) -> None:
        client = _mock_tavily(answer="Aphex Twin is an English electronic musician.")
        with patch("agent.tools.web_search._tavily_client", return_value=client):
            text, artifact = _agentic_search("Aphex Twin", "Aphex Twin musician biography")
        assert client.search.call_count == 1
        assert "Aphex Twin is an English" in text
        assert artifact["confidence"] == "high"

    def test_complex_query_fans_out_and_synthesizes(self) -> None:
        client = _mock_tavily(answer="placeholder")
        complex_query = "compare bossa nova and afrobeat's rhythmic roots and how they evolved?"
        with (
            patch("agent.tools.web_search._tavily_client", return_value=client),
            patch(
                "agent.tools.web_search.decompose_query",
                return_value=[
                    "compare bossa nova and afrobeat's rhythmic roots",
                    "how they evolved?",
                ],
            ),
            patch("agent.tools.web_search.score_complexity", return_value="complex"),
            patch(
                "agent.tools.web_search._synthesize", return_value="Synthesized answer [1][2]"
            ) as mock_synth,
        ):
            text, artifact = _agentic_search("bossa nova vs afrobeat", complex_query)

        assert client.search.call_count == 2
        mock_synth.assert_called_once()
        assert text == "Synthesized answer [1][2]"
        assert artifact["confidence"] == "high"

    def test_low_confidence_returns_honest_non_answer(self) -> None:
        client = _mock_tavily()  # no answer, no results
        with (
            patch("agent.tools.web_search._tavily_client", return_value=client),
            patch(
                "agent.tools.web_search._wikipedia_fallback",
                return_value={"text": "", "sources": [], "confidence": "low"},
            ),
        ):
            text, artifact = _agentic_search(
                "Some Fictional Artist", "Some Fictional Artist biography"
            )

        assert "couldn't find" in text.lower()
        assert artifact == {"sources": [], "confidence": "low"}

    def test_falls_back_to_wikipedia_when_tavily_unavailable(self) -> None:
        fallback = {
            "text": "Genre summary.",
            "sources": [{"title": "X", "url": "https://x.test"}],
            "confidence": "medium",
        }
        with (
            patch("agent.tools.web_search._tavily_client", return_value=None),
            patch("agent.tools.web_search._wikipedia_fallback", return_value=fallback) as mock_wiki,
        ):
            text, artifact = _agentic_search("zouk", "zouk music genre", wiki_query="zouk music")

        mock_wiki.assert_called_once_with("zouk music")
        assert text == "Genre summary."
        assert artifact["confidence"] == "medium"


# =============================================================================
# Tool wrappers — return (content, artifact) for content_and_artifact
# =============================================================================


class TestToolWrappers:
    def test_get_artist_context_returns_content_and_artifact_tuple(self) -> None:
        with patch(
            "agent.tools.web_search._agentic_search",
            return_value=("bio text", {"sources": [], "confidence": "high"}),
        ) as mock_search:
            result = _get_artist_context("Aphex Twin")

        assert result == ("bio text", {"sources": [], "confidence": "high"})
        args, kwargs = mock_search.call_args
        assert args[0] == "Aphex Twin"
        assert kwargs["wiki_query"] == "Aphex Twin"

    def test_get_genre_context_uses_genre_specific_wiki_query(self) -> None:
        with patch(
            "agent.tools.web_search._agentic_search",
            return_value=("genre text", {"sources": [], "confidence": "medium"}),
        ) as mock_search:
            _get_genre_context("zouk")

        assert mock_search.call_args.kwargs["wiki_query"] == "zouk music"
