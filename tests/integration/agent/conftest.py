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
