from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src" / "rag_core"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))


# ---------------------------------------------------------------------------
# fetch_wikipedia
# ---------------------------------------------------------------------------


def test_wikipedia_happy_path():
    """Successful page fetch returns content string."""
    from preprocessing.fetchers import fetch_wikipedia

    mock_page = MagicMock()
    mock_page.content = "Richard David James is a musician..."
    mock_page.url = "https://en.wikipedia.org/wiki/Aphex_Twin"

    with patch("preprocessing.fetchers.wikipedia") as mock_wiki:
        mock_wiki.page.return_value = mock_page
        mock_wiki.exceptions = _wiki_exceptions()

        result = fetch_wikipedia("Aphex Twin")

    assert result == "Richard David James is a musician..."
    mock_wiki.page.assert_called_once_with("Aphex Twin", auto_suggest=True)


def test_wikipedia_disambiguation_fallback():
    """DisambiguationError with options → tries first option."""
    from preprocessing.fetchers import fetch_wikipedia

    mock_page = MagicMock()
    mock_page.content = "Genesis is a band..."
    mock_page.url = "https://en.wikipedia.org/wiki/Genesis_(band)"

    exc_cls = type("DisambiguationError", (Exception,), {})

    with patch("preprocessing.fetchers.wikipedia") as mock_wiki:
        mock_wiki.exceptions = _wiki_exceptions(disambig_cls=exc_cls)

        disambig_error = exc_cls("Genesis")
        disambig_error.options = ["Genesis (band)", "Genesis (video game)"]

        mock_wiki.page.side_effect = [disambig_error, mock_page]

        result = fetch_wikipedia("Genesis")

    assert result == "Genesis is a band..."
    assert mock_wiki.page.call_count == 2


def test_wikipedia_page_not_found():
    """PageError → returns None."""
    from preprocessing.fetchers import fetch_wikipedia

    page_error_cls = type("PageError", (Exception,), {})

    with patch("preprocessing.fetchers.wikipedia") as mock_wiki:
        mock_wiki.exceptions = _wiki_exceptions(page_error_cls=page_error_cls)
        mock_wiki.page.side_effect = page_error_cls("Not found")

        result = fetch_wikipedia("xyznonexistent")

    assert result is None


def test_wikipedia_general_error():
    """WikipediaException → returns None."""
    from preprocessing.fetchers import fetch_wikipedia

    wiki_exc_cls = type("WikipediaException", (Exception,), {})

    with patch("preprocessing.fetchers.wikipedia") as mock_wiki:
        mock_wiki.exceptions = _wiki_exceptions(wiki_exc_cls=wiki_exc_cls)
        mock_wiki.page.side_effect = wiki_exc_cls("Rate limited")

        result = fetch_wikipedia("Radiohead")

    assert result is None


def test_wikipedia_sets_language():
    """Language parameter is passed to wikipedia.set_lang."""
    from preprocessing.fetchers import fetch_wikipedia

    mock_page = MagicMock()
    mock_page.content = "Content"
    mock_page.url = "https://de.wikipedia.org/wiki/Kraftwerk"

    with patch("preprocessing.fetchers.wikipedia") as mock_wiki:
        mock_wiki.page.return_value = mock_page
        mock_wiki.exceptions = _wiki_exceptions()

        fetch_wikipedia("Kraftwerk", language="de")

    mock_wiki.set_lang.assert_called_once_with("de")


# ---------------------------------------------------------------------------
# fetch_tavily
# ---------------------------------------------------------------------------


def test_tavily_no_api_key():
    """Returns None when no TAVILY_API_KEY is set."""
    from preprocessing.fetchers import fetch_tavily

    with patch("preprocessing.fetchers.settings") as mock_settings:
        mock_settings.tavily_api_key = ""
        result = fetch_tavily("Aphex Twin")

    assert result is None


def test_tavily_not_installed():
    """Returns None when tavily package is not installed."""
    import builtins

    from preprocessing.fetchers import fetch_tavily

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "tavily":
            raise ImportError("No module named 'tavily'")
        return real_import(name, *args, **kwargs)

    with (
        patch("preprocessing.fetchers.settings") as mock_settings,
        patch("builtins.__import__", side_effect=mock_import),
    ):
        mock_settings.tavily_api_key = "test-key"
        result = fetch_tavily("Aphex Twin")

    assert result is None


def test_tavily_happy_path():
    """Successful search returns concatenated content."""
    from preprocessing.fetchers import fetch_tavily

    mock_client_cls = MagicMock()
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.search.return_value = {
        "results": [
            {"content": "Result one about the artist."},
            {"content": "Result two with biography."},
        ]
    }

    with (
        patch("preprocessing.fetchers.settings") as mock_settings,
        patch.dict("sys.modules", {"tavily": MagicMock(TavilyClient=mock_client_cls)}),
    ):
        mock_settings.tavily_api_key = "test-key"
        result = fetch_tavily("Aphex Twin")

    assert result is not None
    assert "Result one" in result
    assert "Result two" in result


def test_tavily_connection_error():
    """ConnectionError → returns None."""
    from preprocessing.fetchers import fetch_tavily

    mock_client_cls = MagicMock()
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.search.side_effect = ConnectionError("timeout")

    with (
        patch("preprocessing.fetchers.settings") as mock_settings,
        patch.dict("sys.modules", {"tavily": MagicMock(TavilyClient=mock_client_cls)}),
    ):
        mock_settings.tavily_api_key = "test-key"
        result = fetch_tavily("Aphex Twin")

    assert result is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wiki_exceptions(
    disambig_cls: type | None = None,
    page_error_cls: type | None = None,
    wiki_exc_cls: type | None = None,
) -> MagicMock:
    """Build a mock ``wikipedia.exceptions`` namespace."""
    exc = MagicMock()
    exc.DisambiguationError = disambig_cls or type("DisambiguationError", (Exception,), {})
    exc.PageError = page_error_cls or type("PageError", (Exception,), {})
    exc.WikipediaException = wiki_exc_cls or type("WikipediaException", (Exception,), {})
    return exc
