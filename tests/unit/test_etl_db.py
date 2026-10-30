"""Unit tests for etl.db connection safety."""

import duckdb
import pytest

from etl.db import _is_duckdb_file, fetch_count


class TestIsDuckdbFile:
    def test_real_database(self, tmp_path):
        path = tmp_path / "real.db"
        duckdb.connect(str(path)).close()
        assert _is_duckdb_file(path)

    def test_lfs_pointer(self, tmp_path):
        path = tmp_path / "pointer.db"
        path.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 1\n")
        assert not _is_duckdb_file(path)

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.db"
        path.touch()
        assert not _is_duckdb_file(path)


class TestFetchCount:
    def test_returns_int(self):
        conn = duckdb.connect()
        conn.execute("CREATE TABLE t AS SELECT * FROM range(3)")
        assert fetch_count(conn, "SELECT COUNT(*) FROM t") == 3

    def test_no_rows_raises(self):
        conn = duckdb.connect()
        with pytest.raises(RuntimeError, match="no rows"):
            fetch_count(conn, "SELECT 1 WHERE false")
