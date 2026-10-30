"""
Structured logging via structlog.

Usage:
    from utils.logging import get_logger
    log = get_logger(__name__)
    log.info("playlist.loaded", n_tracks=50, playlist="kozmic blues")
"""

import logging
import sys

import structlog

_QUIET_LOGGERS = ("httpx", "httpcore")


def configure_logging(log_level: str = "INFO", render_json: bool = False) -> None:
    """Configure structlog. Call once at application startup."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    # httpx logs every request URL at INFO — Subsonic token auth (u, t, s) rides in the query.
    for noisy in _QUIET_LOGGERS:
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))

    renderer = (
        structlog.processors.JSONRenderer()
        if render_json
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.set_exc_info,
            structlog.processors.StackInfoRenderer(),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)
