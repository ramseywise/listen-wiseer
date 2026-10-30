"""Unit tests for src/etl/bootstrap.py — synthetic tmp DuckDB, no archived CSVs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest
from structlog.testing import capture_logs

from etl import bootstrap


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """DuckDB with the real schema and a few existing archive rows."""
    path = tmp_path / "lw.db"
    conn = duckdb.connect(str(path))
    bootstrap.init_schema(conn)
    conn.execute("INSERT INTO tracks (track_id, track_name) VALUES ('t1', 'one'), ('t2', 'two')")
    conn.execute(
        "INSERT INTO playlists (playlist_id, playlist_name, status) VALUES ('p1', 'A', 'active')"
    )
    conn.execute("INSERT INTO playlist_tracks VALUES ('p1', 't1', NULL)")
    conn.close()
    return path


def _run_main(db: Path, archived: Path) -> list[dict]:
    with (
        patch("etl.bootstrap.ARCHIVED", archived),
        patch("etl.bootstrap.get_connection", side_effect=lambda: duckdb.connect(str(db))),
        patch("etl.bootstrap._train_if_needed") as train,
        capture_logs() as logs,
    ):
        bootstrap.main()
    train.assert_called_once()
    return logs


def test_main_without_archived_dir_keeps_existing_rows(tmp_db: Path, tmp_path: Path) -> None:
    logs = _run_main(tmp_db, tmp_path / "missing_archived")

    events = [entry["event"] for entry in logs]
    assert "bootstrap.archived.missing" in events
    assert "bootstrap.db.ready" in events
    assert not any(e.endswith(".missing") and e != "bootstrap.archived.missing" for e in events)

    conn = duckdb.connect(str(tmp_db), read_only=True)
    assert conn.execute("SELECT COUNT(*) FROM tracks").fetchall()[0][0] == 2
    assert conn.execute("SELECT COUNT(*) FROM playlist_tracks").fetchall()[0][0] == 1
    assert conn.execute("SELECT COUNT(*) FROM library").fetchall()[0][0] == 0  # schema migrated
    conn.close()


def test_main_without_archived_dir_on_empty_db_creates_schema(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    logs = _run_main(db, tmp_path / "missing_archived")

    ready = next(entry for entry in logs if entry["event"] == "bootstrap.db.ready")
    assert ready["n_tracks"] == 0


def test_main_with_archived_dir_runs_loaders(tmp_db: Path, tmp_path: Path) -> None:
    archived = tmp_path / "archived"
    archived.mkdir()
    with patch("etl.bootstrap._load_archived_csvs") as load:
        logs = _run_main(tmp_db, archived)

    load.assert_called_once()
    assert "bootstrap.archived.missing" not in [entry["event"] for entry in logs]
