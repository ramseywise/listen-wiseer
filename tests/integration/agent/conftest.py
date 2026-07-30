"""Integration agent test fixtures.

Patches the RecommendationEngine so that ``agent.tools`` can be loaded
without a real DuckDB file on disk.  The patch targets the class in
``recommend.engine`` *before* ``agent.tools`` is first imported, then
stays active for the full test session.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _patch_engine():
    """Replace ``_engine`` in agent.tools.recommend with a safe mock.

    Individual tests that need finer control can layer their own
    ``@patch("agent.tools.recommend._engine", ...)`` on top.
    """
    mock_engine = MagicMock()
    with patch("agent.tools.recommend._engine", mock_engine):
        yield mock_engine


@pytest.fixture(autouse=True)
def _disable_verification_retries(monkeypatch: pytest.MonkeyPatch):
    """Zero the checker retry cap for scripted-LLM integration tests.

    These tests feed exact ``side_effect`` response sequences; a HeuristicChecker
    retry consumes the next scripted response out of order and breaks multiturn
    assertions. The verification loop itself is covered by unit tests
    (tests/unit/agent/test_verification.py).
    """
    from utils.config import settings

    monkeypatch.setattr(settings, "max_verification_retries", 0)
