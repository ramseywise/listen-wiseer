"""Unit tests for etl.db connection safety."""

import duckdb

from etl.db import _is_duckdb_file


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
