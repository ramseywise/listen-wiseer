"""Unit tests for recommend.modules.genre loaders against a synthetic genre_xy CSV."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from recommend.modules.genre import expand_genre_zone, load_genre_map


def _write_genre_xy(path: Path) -> Path:
    path.write_text(
        "first_genre,color,top,left\nzouk,#f00,100.0,200.0\nshoegaze,#0f0,5000.0,5000.0\n"
    )
    return path


def test_load_genre_map_keeps_coordinate_columns(tmp_path: Path) -> None:
    df = load_genre_map(_write_genre_xy(tmp_path / "genre_xy.csv"))
    assert df.columns == ["first_genre", "top", "left"]
    assert df.row(0) == ("zouk", 100.0, 200.0)


def test_csv_map_feeds_zone_expansion(tmp_path: Path) -> None:
    genre_map = load_genre_map(_write_genre_xy(tmp_path / "genre_xy.csv"))
    corpus = pl.DataFrame({"id": ["near", "far"], "top": [110.0, 4900.0], "left": [190.0, 5000.0]})
    zone = expand_genre_zone("Zouk", genre_map, corpus, radius=100.0)
    assert zone["id"].to_list() == ["near"]
