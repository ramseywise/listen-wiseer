"""Fixtures for integration tests.

Integration tests require live Spotify OAuth credentials. They are skipped
unless SPOTIFY_CLIENT_ID is present in the environment.

Tests in this directory will be added in Phase 4 when MCP tools are wired
to real Spotify API calls.
"""

import os

import pytest


def pytest_collection_modifyitems(items: list) -> None:
    """Skip all integration tests when Spotify credentials are absent."""
    if os.getenv("SPOTIFY_CLIENT_ID"):
        return
    skip_marker = pytest.mark.skip(reason="SPOTIFY_CLIENT_ID not set — skipping integration tests")
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(skip_marker)
