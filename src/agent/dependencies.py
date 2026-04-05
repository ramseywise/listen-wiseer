"""Agent dependency lifecycle — checkpointer and store initialization."""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Singleton state — set up once at app startup
# ---------------------------------------------------------------------------
_checkpointer: BaseCheckpointSaver | None = None


async def get_checkpointer() -> BaseCheckpointSaver:
    """Return the configured checkpointer, creating it on first call.

    Uses ``AsyncRedisSaver`` when ``REDIS_URL`` is set, otherwise falls back
    to the in-process ``MemorySaver``.
    """
    global _checkpointer  # noqa: PLW0603
    if _checkpointer is not None:
        return _checkpointer

    if settings.redis_url:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver

        ttl_config = {"default_ttl": settings.redis_ttl_minutes * 60}
        saver = AsyncRedisSaver(redis_url=settings.redis_url, ttl=ttl_config)
        await saver.asetup()
        _checkpointer = saver
        log.info("agent.checkpointer.redis", redis_url=settings.redis_url)
    else:
        _checkpointer = MemorySaver()
        log.info("agent.checkpointer.memory")

    return _checkpointer


async def shutdown_checkpointer() -> None:
    """Clean up the checkpointer connection (Redis only)."""
    global _checkpointer  # noqa: PLW0603
    if _checkpointer is not None and hasattr(_checkpointer, "conn"):
        await _checkpointer.conn.aclose()
        log.info("agent.checkpointer.closed")
    _checkpointer = None
