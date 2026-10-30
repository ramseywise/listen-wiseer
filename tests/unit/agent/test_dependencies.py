"""Unit tests for agent.dependencies — checkpointer selection and shutdown.

Postgres / Redis savers are replaced with fakes; nothing connects anywhere.
"""

from __future__ import annotations

import sys
import types
from contextlib import asynccontextmanager

import pytest
from langgraph.checkpoint.memory import MemorySaver

from agent import dependencies
from utils.config import settings


@pytest.fixture(autouse=True)
def _reset_singletons(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dependencies, "_checkpointer", None)
    monkeypatch.setattr(dependencies, "_exit_stack", None)
    monkeypatch.setattr(settings, "postgres_url", "")
    monkeypatch.setattr(settings, "redis_url", "")
    yield


class _FakePostgresSaver:
    instances: list[_FakePostgresSaver] = []

    def __init__(self, conn_str: str) -> None:
        self.conn_str = conn_str
        self.setup_called = False
        self.closed = False
        _FakePostgresSaver.instances.append(self)

    async def setup(self) -> None:
        self.setup_called = True

    @classmethod
    @asynccontextmanager
    async def from_conn_string(cls, conn_str: str):
        saver = cls(conn_str)
        try:
            yield saver
        finally:
            saver.closed = True


class _FakeRedisSaver:
    def __init__(self, *, redis_url: str, ttl: dict) -> None:
        self.redis_url = redis_url
        self.ttl = ttl
        self.setup_called = False

    async def asetup(self) -> None:
        self.setup_called = True


def _install_module(monkeypatch: pytest.MonkeyPatch, name: str, **attrs) -> None:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, name, mod)


async def test_memory_saver_when_no_urls() -> None:
    saver = await dependencies.get_checkpointer()
    assert isinstance(saver, MemorySaver)


async def test_checkpointer_is_singleton() -> None:
    first = await dependencies.get_checkpointer()
    assert await dependencies.get_checkpointer() is first


async def test_postgres_branch_strips_dialect_and_sets_up(monkeypatch) -> None:
    _FakePostgresSaver.instances.clear()
    _install_module(
        monkeypatch, "langgraph.checkpoint.postgres.aio", AsyncPostgresSaver=_FakePostgresSaver
    )
    monkeypatch.setattr(settings, "postgres_url", "postgresql+psycopg://u:p@db:5432/lw")
    monkeypatch.setattr(settings, "redis_url", "redis://ignored:6379")

    saver = await dependencies.get_checkpointer()

    assert isinstance(saver, _FakePostgresSaver)
    assert saver.conn_str == "postgresql://u:p@db:5432/lw"
    assert saver.setup_called
    assert not saver.closed


async def test_shutdown_closes_postgres_connection(monkeypatch) -> None:
    _install_module(
        monkeypatch, "langgraph.checkpoint.postgres.aio", AsyncPostgresSaver=_FakePostgresSaver
    )
    monkeypatch.setattr(settings, "postgres_url", "postgresql://u:p@db/lw")
    saver = await dependencies.get_checkpointer()

    await dependencies.shutdown_checkpointer()

    assert saver.closed
    assert dependencies._checkpointer is None
    assert dependencies._exit_stack is None


async def test_redis_branch_passes_ttl_in_seconds(monkeypatch) -> None:
    _install_module(monkeypatch, "langgraph.checkpoint.redis.aio", AsyncRedisSaver=_FakeRedisSaver)
    monkeypatch.setattr(settings, "redis_url", "redis://cache:6379")
    monkeypatch.setattr(settings, "redis_ttl_minutes", 30)

    saver = await dependencies.get_checkpointer()

    assert isinstance(saver, _FakeRedisSaver)
    assert saver.redis_url == "redis://cache:6379"
    assert saver.ttl == {"default_ttl": 1800}
    assert saver.setup_called


async def test_shutdown_without_exit_stack_resets_singleton() -> None:
    first = await dependencies.get_checkpointer()
    await dependencies.shutdown_checkpointer()
    assert await dependencies.get_checkpointer() is not first
