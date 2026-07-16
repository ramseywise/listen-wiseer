"""Unit tests for src/recommend/modules/genre.py — synthetic fixtures, no real data files."""

from __future__ import annotations

import duckdb
import polars as pl
import pytest
from recommend.modules.genre import (
    expand_genre_zone,
    filter_by_enoa_proximity,
    genre_to_enoa,
    load_genre_map_from_db,
)


@pytest.fixture(scope="module")
def genre_map() -> pl.DataFrame:
    """Synthetic genre_xy table via in-memory DuckDB."""
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE genre_xy (
            first_genre VARCHAR PRIMARY KEY,
            top DOUBLE, "left" DOUBLE, color VARCHAR
        );
        INSERT INTO genre_xy VALUES
            ('zouk', 2862.0, 1004.0, '#ff0000'),
            ('bossa nova', 2000.0, 1200.0, '#00ff00'),
            ('house', 4000.0, 3000.0, '#0000ff'),
            ('jazz', 100.0, 200.0, 'blue'),
            ('son cubano', 300.0, 400.0, 'red');
    """)
    df = load_genre_map_from_db(conn)
    conn.close()
    return df


@pytest.fixture
def small_corpus() -> pl.DataFrame:
    """Small synthetic corpus with top/left ENOA coordinates."""
    return pl.DataFrame(
        {
            "id": ["t1", "t2", "t3", "t4", "t5"],
            "track_name": ["Track A", "Track B", "Track C", "Track D", "Track E"],
            "top": [2862.0, 2000.0, 5000.0, 3000.0, 10000.0],
            "left": [1004.0, 1100.0, 800.0, 950.0, 500.0],
        }
    )


class TestGenreToEnoa:
    def test_known_genre_returns_tuple_of_floats(self, genre_map: pl.DataFrame) -> None:
        result = genre_to_enoa("zouk", genre_map)
        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)

    def test_nonexistent_genre_returns_none(self, genre_map: pl.DataFrame) -> None:
        result = genre_to_enoa("NONEXISTENT_XYZ", genre_map)
        assert result is None

    def test_case_insensitive_exact_match(self, genre_map: pl.DataFrame) -> None:
        lower = genre_to_enoa("zouk", genre_map)
        upper = genre_to_enoa("ZOUK", genre_map)
        mixed = genre_to_enoa("Zouk", genre_map)
        assert lower == upper == mixed

    def test_fuzzy_false_returns_none_on_substring(self, genre_map: pl.DataFrame) -> None:
        # "zou" is a substring of "zouk" — with fuzzy=False should return None
        result = genre_to_enoa("zou", genre_map, fuzzy=False)
        assert result is None

    def test_fuzzy_true_matches_substring(self, genre_map: pl.DataFrame) -> None:
        # "zou" should match "zouk" via substring when fuzzy=True
        result = genre_to_enoa("zou", genre_map, fuzzy=True)
        assert result is not None


class TestFilterByEnoaProximity:
    def test_returns_only_rows_within_radius(self, small_corpus: pl.DataFrame) -> None:
        # zouk is at (2862, 1004); radius=500 should exclude the far point at (10000, 500)
        center = (2862.0, 1004.0)
        result = filter_by_enoa_proximity(small_corpus, center, radius=500.0)
        assert len(result) > 0
        assert all(result["enoa_distance"].to_list()[i] <= 500.0 for i in range(len(result)))
        # t5 at (10000, 500) is very far — must not appear
        assert "t5" not in result["id"].to_list()

    def test_adds_enoa_distance_column_sorted_ascending(self, small_corpus: pl.DataFrame) -> None:
        center = (2862.0, 1004.0)
        result = filter_by_enoa_proximity(small_corpus, center, radius=5000.0)
        assert "enoa_distance" in result.columns
        distances = result["enoa_distance"].to_list()
        assert distances == sorted(distances)

    def test_empty_corpus_returns_empty_dataframe(self) -> None:
        empty = pl.DataFrame({"id": [], "top": [], "left": []})
        result = filter_by_enoa_proximity(empty, (2862.0, 1004.0), radius=1500.0)
        assert len(result) == 0
        assert isinstance(result, pl.DataFrame)

    def test_no_crash_on_empty_corpus(self) -> None:
        """Regression: empty corpus must not raise any exception."""
        empty = pl.DataFrame(
            {
                "id": pl.Series([], dtype=pl.String),
                "top": pl.Series([], dtype=pl.Float64),
                "left": pl.Series([], dtype=pl.Float64),
            }
        )
        result = filter_by_enoa_proximity(empty, (1000.0, 1000.0))
        assert isinstance(result, pl.DataFrame)
        assert len(result) == 0


class TestExpandGenreZone:
    def test_known_genre_returns_nonempty_dataframe(
        self, genre_map: pl.DataFrame, small_corpus: pl.DataFrame
    ) -> None:
        result = expand_genre_zone("zouk", genre_map, small_corpus, radius=5000.0)
        assert isinstance(result, pl.DataFrame)
        assert len(result) > 0

    def test_unknown_genre_returns_empty_dataframe_no_raise(
        self, genre_map: pl.DataFrame, small_corpus: pl.DataFrame
    ) -> None:
        result = expand_genre_zone("NONEXISTENT_XYZ", genre_map, small_corpus)
        assert isinstance(result, pl.DataFrame)
        assert len(result) == 0
