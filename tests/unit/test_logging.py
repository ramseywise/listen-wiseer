"""Unit tests for src/utils/logging.py."""

import logging

import pytest
import structlog

from utils.logging import configure_logging


@pytest.fixture(autouse=True)
def _restore_logging():
    """configure_logging is process-global — put structlog and the loggers back after."""
    levels = {n: logging.getLogger(n).level for n in ("httpx", "httpcore", "")}
    yield
    structlog.reset_defaults()
    for name, level in levels.items():
        logging.getLogger(name or None).setLevel(level)


@pytest.mark.parametrize("name", ["httpx", "httpcore"])
def test_http_client_loggers_quieted(name: str) -> None:
    """Request URLs carry Subsonic auth params — they must not reach INFO logs."""
    configure_logging("INFO")
    logger = logging.getLogger(name)
    assert logger.level == logging.WARNING
    assert not logger.isEnabledFor(logging.INFO)


def test_quiet_loggers_follow_a_stricter_level() -> None:
    configure_logging("ERROR")
    assert logging.getLogger("httpx").level == logging.ERROR
