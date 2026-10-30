from __future__ import annotations

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)


def get_langfuse_handler() -> CallbackHandler | None:
    """Return a LangFuse CallbackHandler if enabled, else None.

    langfuse >= 3 takes credentials on the client, not the handler, and reads
    session/user/trace attributes from the run config instead:
    ``config={"callbacks": [handler], "metadata": {"langfuse_session_id": ...,
    "langfuse_user_id": ...}, "run_name": ...}``.
    """
    if not settings.enable_langfuse or not settings.langfuse_public_key:
        return None
    Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    handler = CallbackHandler(public_key=settings.langfuse_public_key)
    log.info("langfuse.handler.created")
    return handler
