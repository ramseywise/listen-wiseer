"""Unit tests for the memory store factory.

Import/config tests only — no real DB connections.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.store.memory import InMemoryStore
from langgraph.store.postgres import AsyncPostgresStore


@pytest.fixture(autouse=True)
def reset_store_singleton():
    """Reset the singleton between tests to prevent state leakage."""
    import agent.memory_store as ms

    ms._store = None
    ms._store_exit_stack = None
    yield
    ms._store = None
    ms._store_exit_stack = None


async def test_get_store_returns_in_memory_without_url():
    import agent.memory_store as ms

    with patch.object(ms.settings, "memory_store_url", None):
        with patch.object(ms, "SentenceTransformerEmbeddings", return_value=MagicMock()):
            store = await ms.get_store()

    assert isinstance(store, InMemoryStore)


async def test_get_store_returns_cached_store():
    import agent.memory_store as ms

    sentinel = MagicMock(spec=InMemoryStore)
    ms._store = sentinel

    result = await ms.get_store()

    assert result is sentinel


async def test_get_store_returns_postgres_with_url():
    import agent.memory_store as ms

    mock_pg_store = MagicMock(spec=AsyncPostgresStore)
    mock_pg_store.setup = AsyncMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_pg_store)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    url = "postgresql://user:pass@localhost/listen_wiseer"
    with patch.object(ms.settings, "memory_store_url", url):
        with patch.object(ms, "AsyncPostgresStore") as mock_cls:
            mock_cls.from_conn_string.return_value = mock_ctx
            store = await ms.get_store()

    assert store is mock_pg_store
    mock_cls.from_conn_string.assert_called_once_with(url)
    mock_pg_store.setup.assert_awaited_once()


async def test_shutdown_store_clears_singleton():
    import agent.memory_store as ms

    ms._store = MagicMock(spec=InMemoryStore)
    ms._store_exit_stack = None

    await ms.shutdown_store()

    assert ms._store is None
    assert ms._store_exit_stack is None


async def test_shutdown_store_closes_exit_stack():
    """shutdown_store calls aclose on the exit stack when one exists."""
    import agent.memory_store as ms

    mock_stack = AsyncMock()
    ms._store = MagicMock(spec=AsyncPostgresStore)
    ms._store_exit_stack = mock_stack

    await ms.shutdown_store()

    mock_stack.aclose.assert_awaited_once()
    assert ms._store is None
    assert ms._store_exit_stack is None


async def test_get_store_singleton_not_recreated():
    """Calling get_store twice without reset returns the same object."""
    import agent.memory_store as ms

    with patch.object(ms.settings, "memory_store_url", None):
        with patch.object(ms, "SentenceTransformerEmbeddings", return_value=MagicMock()):
            first = await ms.get_store()
            second = await ms.get_store()

    assert first is second
