from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).parents[2]))


def _make_doc(i: int = 0) -> dict:
    return {
        "url": f"https://help.example.com/article/{i}",
        "title": f"Article {i}",
        "section": "general",
        "text": (
            "This help article explains how to configure your account settings. "
            "You can update your name, email address, and notification preferences."
        ),
    }


def _jsonl_response(*docs: dict) -> str:
    return "\n".join(json.dumps(d) for d in docs)


@pytest.fixture
def mock_chunker():
    from preprocessing.chunker import ChunkerConfig, HtmlAwareChunker

    return HtmlAwareChunker(ChunkerConfig(min_tokens=5))


@pytest.fixture
def mock_embedder():
    embedder = MagicMock()
    embedder.embed_passages.side_effect = lambda texts: [[0.1] * 1024 for _ in texts]
    return embedder


@pytest.fixture
def mock_os_client():
    client = MagicMock()
    client.upsert_chunks = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# fetch_docs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_docs_parses_jsonl():
    from ingestion.pipeline import fetch_docs

    docs = [_make_doc(0), _make_doc(1)]
    body = _jsonl_response(*docs)

    with patch("ingestion.pipeline.httpx.AsyncClient") as mock_cls:
        mock_response = MagicMock()
        mock_response.text = body
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await fetch_docs("https://api.example.com/docs", "key-123")

    assert len(result) == 2
    assert result[0]["url"] == "https://help.example.com/article/0"


@pytest.mark.asyncio
async def test_fetch_docs_sends_auth_header():
    from ingestion.pipeline import fetch_docs

    with patch("ingestion.pipeline.httpx.AsyncClient") as mock_cls:
        mock_response = MagicMock()
        mock_response.text = ""
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await fetch_docs("https://api.example.com/docs", "my-api-key")

    call_kwargs = mock_client.get.call_args.kwargs
    assert call_kwargs["headers"]["Authorization"] == "Bearer my-api-key"


# ---------------------------------------------------------------------------
# run_ingestion — dry_run skips upsert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_skips_upsert(mock_chunker, mock_embedder, mock_os_client):
    from ingestion.pipeline import run_ingestion

    docs = [_make_doc(0), _make_doc(1)]

    with patch("ingestion.pipeline.fetch_docs", AsyncMock(return_value=docs)):
        await run_ingestion(
            api_url="https://api.example.com/docs",
            api_key="key",
            chunker=mock_chunker,
            embedder=mock_embedder,
            client=mock_os_client,
            dry_run=True,
        )

    mock_os_client.upsert_chunks.assert_not_called()


@pytest.mark.asyncio
async def test_live_run_calls_upsert(mock_chunker, mock_embedder, mock_os_client):
    from ingestion.pipeline import run_ingestion

    docs = [_make_doc(0), _make_doc(1)]

    with patch("ingestion.pipeline.fetch_docs", AsyncMock(return_value=docs)):
        await run_ingestion(
            api_url="https://api.example.com/docs",
            api_key="key",
            chunker=mock_chunker,
            embedder=mock_embedder,
            client=mock_os_client,
            dry_run=False,
        )

    mock_os_client.upsert_chunks.assert_called_once()


# ---------------------------------------------------------------------------
# run_ingestion — chunk count and embedding assignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embeddings_assigned_to_chunks(mock_chunker, mock_embedder, mock_os_client):
    from ingestion.pipeline import run_ingestion

    docs = [_make_doc(0)]

    with patch("ingestion.pipeline.fetch_docs", AsyncMock(return_value=docs)):
        await run_ingestion(
            api_url="https://api.example.com/docs",
            api_key="key",
            chunker=mock_chunker,
            embedder=mock_embedder,
            client=mock_os_client,
            dry_run=False,
        )

    upserted_chunks = mock_os_client.upsert_chunks.call_args.args[0]
    assert all(c.embedding is not None for c in upserted_chunks)
    assert all(len(c.embedding) == 1024 for c in upserted_chunks)


@pytest.mark.asyncio
async def test_embed_passages_called_with_all_chunk_texts(
    mock_chunker, mock_embedder, mock_os_client
):
    from ingestion.pipeline import run_ingestion

    docs = [_make_doc(i) for i in range(3)]

    with patch("ingestion.pipeline.fetch_docs", AsyncMock(return_value=docs)):
        await run_ingestion(
            api_url="https://api.example.com/docs",
            api_key="key",
            chunker=mock_chunker,
            embedder=mock_embedder,
            client=mock_os_client,
            dry_run=True,
        )

    call_texts = mock_embedder.embed_passages.call_args.args[0]
    assert len(call_texts) > 0
    assert all(isinstance(t, str) for t in call_texts)
