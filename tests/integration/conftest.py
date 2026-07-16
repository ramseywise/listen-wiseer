"""Fixtures for integration tests.

Integration tests require external resources (DuckDB file, Spotify OAuth,
Redis). They are skipped when the required resource is unavailable.

Tests that don't need external resources can opt out of the auto-skip by
adding ``@pytest.mark.integration`` (which runs unconditionally).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def _duckdb_available() -> bool:
    """Check whether the LFS-tracked DuckDB file is readable."""
    try:
        import duckdb
        from paths import DB_PATH

        if not Path(DB_PATH).exists():
            return False
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        conn.close()
        return True
    except Exception:
        return False


_DUCKDB_OK = _duckdb_available()
_SPOTIFY_OK = bool(os.getenv("SPOTIFY_CLIENT_ID"))


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip integration tests when required resources are absent.

    Tests marked with ``@pytest.mark.integration`` are never auto-skipped —
    they declare that they manage their own resource requirements.
    """
    for item in items:
        path_str = str(item.path)
        if "integration" not in path_str:
            continue

        # Tests that explicitly declare @pytest.mark.integration handle their own deps
        if item.get_closest_marker("integration"):
            continue

        # Agent/MCP tests need the DuckDB file for engine import
        if not _DUCKDB_OK:
            item.add_marker(pytest.mark.skip(reason="DuckDB file not available (git-lfs)"))
        # Spotify tests also need credentials
        if not _SPOTIFY_OK and "spotify" in path_str.lower():
            item.add_marker(pytest.mark.skip(reason="SPOTIFY_CLIENT_ID not set"))
