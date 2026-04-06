from __future__ import annotations

from langfuse.langchain import CallbackHandler

from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)


def get_langfuse_handler(
    session_id: str | None = None,
    user_id: str | None = None,
    trace_name: str = "listen-wiseer",
) -> CallbackHandler | None:
    """Return a LangFuse CallbackHandler if enabled, else None."""
    if not settings.enable_langfuse or not settings.langfuse_public_key:
        return None
    handler = CallbackHandler(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
        session_id=session_id,
        user_id=user_id,
        trace_name=trace_name,
    )
    log.info("langfuse.handler.created", session_id=session_id)
    return handler
