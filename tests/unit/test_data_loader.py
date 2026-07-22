"""Tests for data/loader.py — Polars transforms and file loading."""

from pathlib import Path
from unittest.mock import patch

import polars as pl

from etl.loader import (
    enrich_categorical_features,
    load_listening_history,
    load_playlist_csvs,
    tag_genre_categories,
)


class TestEnrichCategoricalFeatures:
    def test_decade_derived(self, sample_tracks_df: pl.DataFrame):
        result = enrich_categorical_features(sample_tracks_df)
        decades = result["decade"].to_list()
        assert decades[0] == "1970s"
        assert decades[1] == "1990s"
        assert decades[2] == "2010s"

    def test_year_derived(self, sample_tracks_df: pl.DataFrame):
        result = enrich_categorical_features(sample_tracks_df)
        assert result["year"].to_list() == [1973, 1995, 2010]

    def test_key_mode_label(self, sample_tracks_df: pl.DataFrame):
        result = enrich_categorical_features(sample_tracks_df)
        key_modes = result["key_mode"].to_list()
        # key=7 (G) + mode=0 (Minor) → "G Minor"
        assert key_modes[0] == "G Minor"
        # key=0 (C) + mode=1 (Major) → "C Major"
        assert key_modes[1] == "C Major"
        # key=11 (B) + mode=1 (Major) → "B Major"
        assert key_modes[2] == "B Major"

    def test_output_has_all_input_columns(self, sample_tracks_df: pl.DataFrame):
        result = enrich_categorical_features(sample_tracks_df)
        for col in sample_tracks_df.columns:
            assert col in result.columns


class TestTagGenreCategories:
    def test_known_genres_tagged(self, sample_tracks_df: pl.DataFrame):
        result = tag_genre_categories(sample_tracks_df, genre_col="genres")
        cats = result["genre_cat"].to_list()
        # "rock, classic rock" → rock
        assert cats[0] == "rock"
        # "jazz, bossa nova" → jazz or bossa nova (first match wins)
        assert cats[1] in ("jazz", "bossa nova")
        # "zouk" → zouk
        assert cats[2] == "zouk"

    def test_unknown_genre_is_null(self):
        df = pl.DataFrame({"genres": ["unknown experimental noise"]})
        result = tag_genre_categories(df, genre_col="genres")
        assert result["genre_cat"][0] is None


class TestLoadListeningHistory:
    def test_loads_multiple_files(self, listening_history_dir: Path):
        with patch("etl.loader.settings") as mock_settings:
            mock_settings.listening_history_path = str(listening_history_dir)
            result = load_listening_history()

        # Two files: 2 entries + 1 entry = 3 rows
        assert len(result) == 3

    def test_column_names_normalised(self, listening_history_dir: Path):
        with patch("etl.loader.settings") as mock_settings:
            mock_settings.listening_history_path = str(listening_history_dir)
            result = load_listening_history()

        assert "track_name" in result.columns
        assert "artist_name" in result.columns
        assert "master_metadata_track_name" not in result.columns

    def test_empty_dir_returns_empty_df(self, tmp_path: Path):
        with patch("etl.loader.settings") as mock_settings:
            mock_settings.listening_history_path = str(tmp_path)
            result = load_listening_history()

        assert len(result) == 0


class TestLoadPlaylistCsvs:
    def test_concatenates_csvs(self, tmp_path: Path):
        (tmp_path / "a.csv").write_text("id,track_name\nt1,Song A\n")
        (tmp_path / "b.csv").write_text("id,track_name\nt2,Song B\nt3,Song C\n")

        result = load_playlist_csvs(str(tmp_path))
        assert len(result) == 3
        assert set(result["id"].to_list()) == {"t1", "t2", "t3"}

    def test_empty_folder_returns_empty_df(self, tmp_path: Path):
        result = load_playlist_csvs(str(tmp_path))
        assert len(result) == 0
