"""Agent dependency lifecycle — checkpointer and store initialization."""

from __future__ import annotations

from contextlib import AsyncExitStack

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Singleton state — set up once at app startup
# Priority: POSTGRES_URL > REDIS_URL > MemorySaver (dev only)
# ---------------------------------------------------------------------------
_checkpointer: BaseCheckpointSaver | None = None
_exit_stack: AsyncExitStack | None = None


async def get_checkpointer() -> BaseCheckpointSaver:
    """Return the configured checkpointer, creating it on first call."""
    global _checkpointer, _exit_stack  # noqa: PLW0603
    if _checkpointer is not None:
        return _checkpointer

    if settings.postgres_url:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        # from_conn_string is an asynccontextmanager — use AsyncExitStack to
        # enter it once and hold the connection open for the process lifetime.
        # psycopg doesn't accept the SQLAlchemy dialect prefix; strip it.
        conn_str = settings.postgres_url.replace("postgresql+psycopg://", "postgresql://")
        _exit_stack = AsyncExitStack()
        saver = await _exit_stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(conn_str)
        )
        await saver.setup()
        _checkpointer = saver
        log.info("agent.checkpointer.postgres")
    elif settings.redis_url:
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
    """Clean up the checkpointer connection on app shutdown."""
    global _checkpointer, _exit_stack  # noqa: PLW0603
    if _exit_stack is not None:
        await _exit_stack.aclose()
        _exit_stack = None
    _checkpointer = None
    log.info("agent.checkpointer.closed")
