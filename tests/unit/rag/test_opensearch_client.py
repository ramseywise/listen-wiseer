from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from retrieval.client import OpenSearchClient, OpenSearchSettings


def _make_settings() -> OpenSearchSettings:
    return OpenSearchSettings(
        url="https://localhost:9200",
        index="test-index",
        user="admin",
        password="secret",
    )


def _make_hit(doc_id: str = "chunk-1", score: float = 0.9) -> dict:
    return {
        "_id": doc_id,
        "_score": score,
        "_source": {
            "text": "How to reset your password.",
            "title": "Account Help",
            "section": "account",
            "url": "https://help.example.com/account",
            "language": "da",
        },
    }


@pytest.fixture
def mock_os_client():
    """Patch AsyncOpenSearch so no real connection is made."""
    with patch("retrieval.client.AsyncOpenSearch") as mock_cls:
        instance = AsyncMock()
        mock_cls.return_value = instance
        yield instance


# ---------------------------------------------------------------------------
# ensure_index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_index_creates_when_missing(mock_os_client):
    mock_os_client.indices.exists = AsyncMock(return_value=False)
    mock_os_client.indices.create = AsyncMock()

    client = OpenSearchClient(_make_settings())
    await client.ensure_index(dims=1024)

    mock_os_client.indices.create.assert_called_once()
    call_kwargs = mock_os_client.indices.create.call_args
    body = call_kwargs.kwargs.get("body") or call_kwargs.args[1]
    assert body["mappings"]["properties"]["embedding"]["dimension"] == 1024
    assert body["settings"]["index"]["knn"] is True


@pytest.mark.asyncio
async def test_ensure_index_skips_when_exists(mock_os_client):
    mock_os_client.indices.exists = AsyncMock(return_value=True)
    mock_os_client.indices.create = AsyncMock()

    client = OpenSearchClient(_make_settings())
    await client.ensure_index()

    mock_os_client.indices.create.assert_not_called()


# ---------------------------------------------------------------------------
# hybrid_search — query shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_search_query_shape(mock_os_client):
    mock_os_client.search = AsyncMock(return_value={"hits": {"hits": [_make_hit()]}})

    client = OpenSearchClient(_make_settings())
    results = await client.hybrid_search(
        query_text="reset password",
        query_vector=[0.1] * 1024,
        k=5,
    )

    assert len(results) == 1
    assert results[0].score == 0.9
    assert results[0].chunk.id == "chunk-1"

    call_body = mock_os_client.search.call_args.kwargs["body"]
    assert "hybrid" in call_body["query"]
    queries = call_body["query"]["hybrid"]["queries"]
    assert any("match" in q for q in queries)
    assert any("knn" in q for q in queries)
    assert call_body["size"] == 5


@pytest.mark.asyncio
async def test_hybrid_search_applies_section_filter(mock_os_client):
    mock_os_client.search = AsyncMock(return_value={"hits": {"hits": []}})

    client = OpenSearchClient(_make_settings())
    await client.hybrid_search(
        query_text="export data",
        query_vector=[0.0] * 1024,
        k=3,
        section_filter=["billing", "account"],
    )

    call_body = mock_os_client.search.call_args.kwargs["body"]
    assert "bool" in call_body["query"]
    assert "filter" in call_body["query"]["bool"]
    terms = call_body["query"]["bool"]["filter"]["terms"]["section"]
    assert set(terms) == {"billing", "account"}


@pytest.mark.asyncio
async def test_hybrid_search_no_section_filter_omits_bool(mock_os_client):
    mock_os_client.search = AsyncMock(return_value={"hits": {"hits": []}})

    client = OpenSearchClient(_make_settings())
    await client.hybrid_search(
        query_text="login error",
        query_vector=[0.0] * 1024,
    )

    call_body = mock_os_client.search.call_args.kwargs["body"]
    assert "hybrid" in call_body["query"]
    assert "bool" not in call_body["query"]


# ---------------------------------------------------------------------------
# upsert_chunks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_chunks_bulk_called(mock_os_client):
    from schemas.chunks import Chunk, ChunkMetadata

    mock_os_client.bulk = AsyncMock(return_value={"errors": False})

    chunk = Chunk(
        id="c1",
        text="Some help text",
        metadata=ChunkMetadata(
            url="https://help.example.com/page",
            title="Page Title",
            section="general",
            doc_id="c1",
        ),
        embedding=[0.5] * 1024,
    )

    client = OpenSearchClient(_make_settings())
    await client.upsert_chunks([chunk])

    mock_os_client.bulk.assert_called_once()
    body = mock_os_client.bulk.call_args.kwargs["body"]
    # alternating action / doc pairs
    assert body[0] == {"index": {"_index": "test-index", "_id": "c1"}}
    assert body[1]["text"] == "Some help text"
    assert body[1]["embedding"] == [0.5] * 1024


@pytest.mark.asyncio
async def test_upsert_chunks_empty_list_skips_bulk(mock_os_client):
    mock_os_client.bulk = AsyncMock()

    client = OpenSearchClient(_make_settings())
    await client.upsert_chunks([])

    mock_os_client.bulk.assert_not_called()
