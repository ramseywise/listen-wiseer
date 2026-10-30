"""Unit tests for src/utils/doctor.py — tmp DuckDB + tmp models dir, no real data."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from utils.doctor import API_KEYS, check_keys, main, render, run_checks

SECRET = "sk-super-secret-value-123"


def _keys(**overrides: str) -> SimpleNamespace:
    values = dict.fromkeys((name for name, _ in API_KEYS), "")
    values.update(overrides)
    return SimpleNamespace(**values)


def _db(path: Path, n_plays: int) -> Path:
    conn = duckdb.connect(str(path))
    conn.execute("CREATE TABLE plays (track_id VARCHAR)")
    conn.execute("CREATE TABLE tracks (track_id VARCHAR)")
    conn.execute("INSERT INTO tracks VALUES ('t1'), ('t2')")
    if n_plays:
        conn.executemany("INSERT INTO plays VALUES (?)", [[f"p{i}"] for i in range(n_plays)])
    conn.close()
    return path


def _trained(tmp_path: Path) -> tuple[Path, Path]:
    models, cache = tmp_path / "models", tmp_path / "cache"
    models.mkdir()
    cache.mkdir()
    for name in ("gmm_corpus.pkl", "scaler_corpus.pkl", "classifier_x.pkl"):
        (models / name).write_bytes(b"x")
    (cache / "corpus_features.parquet").write_bytes(b"x")
    return models, cache


def test_check_keys_bool_only() -> None:
    keys = check_keys(_keys(anthropic_api_key=SECRET, tavily_api_key="  "))
    assert keys["anthropic_api_key"] is True
    assert keys["tavily_api_key"] is False
    assert set(keys.values()) <= {True, False}


def test_check_keys_tolerates_missing_attributes() -> None:
    assert not any(check_keys(SimpleNamespace()).values())


def test_render_never_leaks_key_values(tmp_path: Path) -> None:
    models, cache = _trained(tmp_path)
    report = run_checks(_keys(anthropic_api_key=SECRET), _db(tmp_path / "a.db", 1), models, cache)
    out = render(report)
    assert SECRET not in out
    assert "ANTHROPIC_API_KEY" in out


def test_all_good_has_no_warnings(tmp_path: Path) -> None:
    models, cache = _trained(tmp_path)
    report = run_checks(_keys(anthropic_api_key="k"), _db(tmp_path / "a.db", 3), models, cache)
    assert report.warnings == []
    assert report.table_counts == {"plays": 3, "tracks": 2}
    assert report.n_classifiers == 1
    assert "All checks passed." in render(report)


def test_empty_plays_warns(tmp_path: Path) -> None:
    models, cache = _trained(tmp_path)
    report = run_checks(_keys(anthropic_api_key="k"), _db(tmp_path / "a.db", 0), models, cache)
    assert any("`plays` is empty" in w for w in report.warnings)


def test_missing_models_and_key_warn(tmp_path: Path) -> None:
    report = run_checks(_keys(), _db(tmp_path / "a.db", 1), tmp_path / "nomodels", tmp_path)
    joined = " ".join(report.warnings)
    assert "make train" in joined
    assert "ANTHROPIC_API_KEY" in joined
    assert report.models == {"gmm_corpus.pkl": False, "scaler_corpus.pkl": False}


def test_missing_db(tmp_path: Path) -> None:
    models, cache = _trained(tmp_path)
    report = run_checks(_keys(anthropic_api_key="k"), tmp_path / "none.db", models, cache)
    assert not report.db_ok
    assert report.db_error == "missing"


def test_lfs_pointer_db(tmp_path: Path) -> None:
    models, cache = _trained(tmp_path)
    ptr = tmp_path / "ptr.db"
    ptr.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 1\n")
    report = run_checks(_keys(anthropic_api_key="k"), ptr, models, cache)
    assert "git lfs pull" in (report.db_error or "")
    assert ptr.read_text().startswith("version https://git-lfs")  # untouched


@pytest.mark.parametrize("strict,expected", [(False, 0), (True, 1)])
def test_main_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, strict: bool, expected: int
) -> None:
    monkeypatch.setattr(
        "utils.doctor.run_checks",
        lambda s: run_checks(s, tmp_path / "none.db", tmp_path, tmp_path),
    )
    assert main(["--strict"] if strict else []) == expected
