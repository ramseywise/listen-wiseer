"""Tests for recommend.preprocessing — all with synthetic fixtures (in-memory DuckDB)."""

from __future__ import annotations

import duckdb
import numpy as np
import polars as pl
import pytest
from recommend.preprocessing import (
    IMPUTABLE_AUDIO_FEATURES,
    add_collaborative_features,
    add_temporal_features,
    build_feature_matrix,
    compute_artist_enoa_centroid,
    compute_artist_medians,
    compute_genre_medians,
    compute_track2vec,
    impute_missing_features,
    load_corpus_from_db,
    load_track2vec,
    propagate_playlist_profiles,
    store_track2vec,
)

# ---------------------------------------------------------------------------
# Fixtures — in-memory DuckDB with synthetic data
# ---------------------------------------------------------------------------


@pytest.fixture
def mem_conn() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB connection with full schema and synthetic data."""
    conn = duckdb.connect(":memory:")

    # Create schema (simplified version of etl/db.py DDL)
    conn.execute("""
        CREATE TABLE playlists (
            playlist_id VARCHAR PRIMARY KEY,
            playlist_name VARCHAR,
            gen_4 VARCHAR,
            gen_6 VARCHAR,
            gen_8 VARCHAR,
            top_genres VARCHAR,
            other_genres VARCHAR,
            include_in_refresh BOOLEAN DEFAULT TRUE,
            last_synced TIMESTAMP
        );

        CREATE TABLE artists (
            artist_id VARCHAR PRIMARY KEY,
            artist_name VARCHAR,
            popularity DOUBLE,
            genres VARCHAR
        );

        CREATE TABLE genre_map (
            first_genre VARCHAR PRIMARY KEY,
            gen_4 VARCHAR, gen_6 VARCHAR, gen_8 VARCHAR,
            my_genre VARCHAR, sub_genre VARCHAR,
            top DOUBLE, "left" DOUBLE, color VARCHAR
        );

        CREATE TABLE tracks (
            track_id VARCHAR PRIMARY KEY,
            track_name VARCHAR,
            release_date VARCHAR,
            year INTEGER,
            decade VARCHAR,
            popularity DOUBLE,
            first_genre VARCHAR,
            genre_cat VARCHAR
        );

        CREATE TABLE audio_features (
            track_id VARCHAR PRIMARY KEY,
            danceability DOUBLE, energy DOUBLE, loudness DOUBLE,
            speechiness DOUBLE, acousticness DOUBLE, instrumentalness DOUBLE,
            liveness DOUBLE, valence DOUBLE, tempo DOUBLE,
            duration_ms BIGINT, time_signature INTEGER,
            key INTEGER, mode INTEGER,
            key_labels VARCHAR, mode_labels VARCHAR, key_mode VARCHAR,
            features_source VARCHAR DEFAULT 'spotify'
        );

        CREATE TABLE genre_xy (
            first_genre VARCHAR PRIMARY KEY,
            top DOUBLE, "left" DOUBLE, color VARCHAR
        );

        CREATE TABLE playlist_tracks (
            playlist_id VARCHAR, track_id VARCHAR,
            PRIMARY KEY (playlist_id, track_id)
        );

        CREATE TABLE track_artists (
            track_id VARCHAR, artist_id VARCHAR,
            PRIMARY KEY (track_id, artist_id)
        );

        CREATE TABLE faves (
            track_id VARCHAR PRIMARY KEY,
            score DOUBLE
        );

        CREATE TABLE track_embeddings (
            track_id VARCHAR PRIMARY KEY,
            embedding DOUBLE[64],
            model_version VARCHAR DEFAULT 'track2vec_v1'
        );

        CREATE OR REPLACE VIEW track_profile AS
        SELECT
            t.track_id, t.track_name, t.release_date, t.year, t.decade,
            t.popularity, t.first_genre, t.genre_cat,
            gm.gen_4, gm.gen_6, gm.gen_8, gm.my_genre, gm.sub_genre,
            gm.top, gm."left", gm.color,
            af.danceability, af.energy, af.loudness, af.speechiness,
            af.acousticness, af.instrumentalness, af.liveness, af.valence,
            af.tempo, af.duration_ms, af.time_signature, af.key, af.mode,
            af.key_labels, af.mode_labels, af.key_mode,
            af.features_source,
            COALESCE(f.score, 0.0) AS fave_score
        FROM tracks t
        LEFT JOIN audio_features af USING (track_id)
        LEFT JOIN genre_map gm ON t.first_genre = gm.first_genre
        LEFT JOIN faves f USING (track_id);
    """)

    # Seed data
    conn.execute("""
        INSERT INTO playlists VALUES
            ('p1', 'Jazz Vibes', 'instrumental', NULL, NULL, NULL, NULL, TRUE, NULL),
            ('p2', 'Dance Floor', 'dance', NULL, NULL, NULL, NULL, TRUE, NULL);
    """)
    conn.execute("""
        INSERT INTO artists VALUES
            ('a1', 'Miles Davis', 85.0, 'jazz, trumpet jazz'),
            ('a2', 'Buena Vista', 70.0, 'son cubano, latin jazz'),
            ('a3', 'Unknown Artist', 10.0, NULL);
    """)
    conn.execute("""
        INSERT INTO genre_map VALUES
            ('jazz', 'instrumental', 'jazz', 'jazz', 'jazz', 'jazz', 100.0, 200.0, 'blue'),
            ('son cubano', 'dance', 'latin', 'latin', 'latin', 'latin', 300.0, 400.0, 'red');
    """)
    conn.execute("""
        INSERT INTO genre_xy VALUES
            ('jazz', 100.0, 200.0, 'blue'),
            ('trumpet jazz', 110.0, 210.0, 'blue'),
            ('son cubano', 300.0, 400.0, 'red'),
            ('latin jazz', 150.0, 250.0, 'green');
    """)
    conn.execute("""
        INSERT INTO tracks VALUES
            ('t1', 'So What', '1959-08-17', 1959, '1950s', 80.0, 'jazz', 'jazz'),
            ('t2', 'Blue in Green', '1959-08-17', 1959, '1950s', 75.0, 'jazz', 'jazz'),
            ('t3', 'Chan Chan', '1997-09-12', 1997, '1990s', 90.0, 'son cubano', 'latin'),
            ('t4', 'New Track', '2024-01-01', 2024, '2020s', 50.0, 'jazz', 'jazz');
    """)
    # t1, t2, t3 have Spotify audio features; t4 has NONE (needs imputation)
    conn.execute("""
        INSERT INTO audio_features (track_id, danceability, energy, loudness, speechiness,
            acousticness, instrumentalness, liveness, valence, tempo,
            duration_ms, time_signature, key, mode, key_labels, mode_labels, key_mode,
            features_source)
        VALUES
            ('t1', 0.4, 0.5, -10.0, 0.03, 0.8, 0.7, 0.1, 0.3, 135.0, 320000, 4, 2, 1, 'D', 'Major', 'D Major', 'spotify'),
            ('t2', 0.3, 0.3, -15.0, 0.02, 0.9, 0.8, 0.05, 0.2, 110.0, 340000, 4, 7, 0, 'G', 'Minor', 'G Minor', 'spotify'),
            ('t3', 0.8, 0.7, -6.0, 0.05, 0.4, 0.1, 0.2, 0.8, 100.0, 260000, 4, 0, 1, 'C', 'Major', 'C Major', 'spotify');
    """)
    conn.execute("""
        INSERT INTO playlist_tracks VALUES
            ('p1', 't1'), ('p1', 't2'), ('p1', 't4'),
            ('p2', 't3'), ('p2', 't1');
    """)
    conn.execute("""
        INSERT INTO track_artists VALUES
            ('t1', 'a1'), ('t2', 'a1'), ('t3', 'a2'), ('t4', 'a3');
    """)
    conn.execute("INSERT INTO faves VALUES ('t1', 5.0), ('t3', 3.0)")

    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoadCorpus:
    def test_load_corpus_from_db(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        df = load_corpus_from_db(mem_conn)
        assert len(df) == 4
        assert "id" in df.columns  # renamed from track_id
        assert "danceability" in df.columns
        assert "features_source" in df.columns

    def test_load_corpus_has_fave_score(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        df = load_corpus_from_db(mem_conn)
        assert "fave_score" in df.columns


class TestTrack2Vec:
    def test_compute_track2vec_dimensions(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        embeddings = compute_track2vec(mem_conn, dim=16, window=3, seed=42)
        # 4 unique tracks across 2 playlists
        assert len(embeddings) >= 3  # at least tracks in playlists
        for _tid, emb in embeddings.items():
            assert emb.shape == (16,)
            assert emb.dtype == np.float64

    def test_store_and_load_track2vec(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        embeddings = compute_track2vec(mem_conn, dim=64, seed=42)
        n_stored = store_track2vec(mem_conn, embeddings, model_version="test_v1")
        assert n_stored == len(embeddings)

        loaded = load_track2vec(mem_conn)
        assert len(loaded) == len(embeddings)
        for tid in embeddings:
            np.testing.assert_allclose(loaded[tid], embeddings[tid], atol=1e-10)

    def test_store_track2vec_replaces_by_version(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        emb1 = {"t1": np.ones(64), "t2": np.zeros(64)}
        store_track2vec(mem_conn, emb1, model_version="v1")
        emb2 = {"t1": np.full(64, 2.0)}
        store_track2vec(mem_conn, emb2, model_version="v1")
        loaded = load_track2vec(mem_conn)
        # v1 was cleared and replaced with emb2 only
        assert len(loaded) == 1
        np.testing.assert_allclose(loaded["t1"], np.full(64, 2.0))


class TestImputationCascade:
    def test_artist_medians_computed(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        corpus = load_corpus_from_db(mem_conn)
        medians = compute_artist_medians(corpus, mem_conn)
        assert "artist_id" in medians.columns
        # a1 has 2 tracks (t1, t2) with spotify features
        a1_row = medians.filter(pl.col("artist_id") == "a1")
        assert a1_row.height == 1
        # Median danceability of t1 (0.4) and t2 (0.3) = 0.35
        assert abs(a1_row["danceability"].item() - 0.35) < 0.01

    def test_genre_medians_computed(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        corpus = load_corpus_from_db(mem_conn)
        medians = compute_genre_medians(corpus)
        jazz_row = medians.filter(pl.col("first_genre") == "jazz")
        assert jazz_row.height == 1

    def test_impute_cascade_artist_first(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        """t4 is by a3 (no tracks with features). Should fall through to genre-median."""
        corpus = load_corpus_from_db(mem_conn)
        artist_medians = compute_artist_medians(corpus, mem_conn)
        genre_medians = compute_genre_medians(corpus)

        result = impute_missing_features(corpus, artist_medians, genre_medians, mem_conn)

        # t4 had NULL features — should now be imputed
        t4 = result.filter(pl.col("id") == "t4")
        assert t4.height == 1
        assert t4["danceability"].item() is not None
        # a3 has no tracks with features → artist median doesn't help
        # t4 first_genre='jazz' → genre median from t1+t2
        source = t4["features_source"].item()
        assert source in ("imputed_genre", "imputed_global")

    def test_impute_no_nulls_remain(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        corpus = load_corpus_from_db(mem_conn)
        artist_medians = compute_artist_medians(corpus, mem_conn)
        genre_medians = compute_genre_medians(corpus)
        result = impute_missing_features(corpus, artist_medians, genre_medians, mem_conn)
        for f in IMPUTABLE_AUDIO_FEATURES:
            null_count = result[f].null_count()
            assert null_count == 0, f"{f} still has {null_count} NULLs after imputation"


class TestCollaborativeFeatures:
    def test_n_playlists(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        corpus = load_corpus_from_db(mem_conn)
        result = add_collaborative_features(corpus, mem_conn)
        assert "n_playlists" in result.columns
        # t1 is in p1 and p2
        t1 = result.filter(pl.col("id") == "t1")
        assert t1["n_playlists"].item() == 2.0
        # t4 is in p1 only
        t4 = result.filter(pl.col("id") == "t4")
        assert t4["n_playlists"].item() == 1.0

    def test_playlist_diversity(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        corpus = load_corpus_from_db(mem_conn)
        result = add_collaborative_features(corpus, mem_conn)
        # t1 is in p1 (instrumental) and p2 (dance) → diversity = 2
        t1 = result.filter(pl.col("id") == "t1")
        assert t1["playlist_diversity"].item() == 2.0

    def test_fave_score(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        corpus = load_corpus_from_db(mem_conn)
        result = add_collaborative_features(corpus, mem_conn)
        t1 = result.filter(pl.col("id") == "t1")
        assert t1["fave_score"].item() == 5.0
        # t2 has no fave → 0.0
        t2 = result.filter(pl.col("id") == "t2")
        assert t2["fave_score"].item() == 0.0


class TestTemporalFeatures:
    def test_year_normalized(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        corpus = load_corpus_from_db(mem_conn)
        result = add_temporal_features(corpus)
        assert "year_normalized" in result.columns
        # Range: 1959 to 2024. t4 (2024) should be 1.0, t1 (1959) should be 0.0
        t4 = result.filter(pl.col("id") == "t4")
        assert abs(t4["year_normalized"].item() - 1.0) < 0.01
        t1 = result.filter(pl.col("id") == "t1")
        assert abs(t1["year_normalized"].item() - 0.0) < 0.01

    def test_years_since_release(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        corpus = load_corpus_from_db(mem_conn)
        result = add_temporal_features(corpus)
        assert "years_since_release" in result.columns
        t4 = result.filter(pl.col("id") == "t4")
        # 2026 - 2024 = 2
        assert t4["years_since_release"].item() == 2.0

    def test_duration_ms_normalized(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        corpus = load_corpus_from_db(mem_conn)
        result = add_temporal_features(corpus)
        assert "duration_ms_normalized" in result.columns
        # All values should be between 0 and 1 (or 0.5 for NULL)
        vals = result["duration_ms_normalized"].to_list()
        for v in vals:
            assert 0.0 <= v <= 1.0


class TestArtistEnoa:
    def test_centroid_computed(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        result = compute_artist_enoa_centroid(mem_conn)
        assert "artist_id" in result.columns
        assert "artist_enoa_top" in result.columns
        assert "artist_enoa_left" in result.columns

        # a1 genres: "jazz, trumpet jazz" → avg of (100, 200) and (110, 210)
        a1 = result.filter(pl.col("artist_id") == "a1")
        assert a1.height == 1
        assert abs(a1["artist_enoa_top"].item() - 105.0) < 0.01
        assert abs(a1["artist_enoa_left"].item() - 205.0) < 0.01

    def test_no_genre_match_excluded(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        result = compute_artist_enoa_centroid(mem_conn)
        # a3 has NULL genres → excluded
        a3 = result.filter(pl.col("artist_id") == "a3")
        assert a3.height == 0


class TestPlaylistPropagation:
    def test_propagated_columns_exist(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        corpus = load_corpus_from_db(mem_conn)
        result = propagate_playlist_profiles(corpus, mem_conn)
        # Should have pp_* columns for imputable audio features
        pp_cols = [c for c in result.columns if c.startswith("pp_")]
        assert len(pp_cols) > 0

    def test_tracks_in_playlists_get_values(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        corpus = load_corpus_from_db(mem_conn)
        result = propagate_playlist_profiles(corpus, mem_conn)
        # t1 is in 2 playlists → should have pp_ values
        t1 = result.filter(pl.col("id") == "t1")
        assert t1["pp_danceability"].item() is not None


class TestBuildFeatureMatrix:
    def test_build_returns_all_rows(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        df = build_feature_matrix(mem_conn)
        assert len(df) == 4

    def test_build_no_null_audio_features(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        df = build_feature_matrix(mem_conn)
        for f in IMPUTABLE_AUDIO_FEATURES:
            assert df[f].null_count() == 0, f"{f} has NULLs in final output"

    def test_build_has_engineered_columns(self, mem_conn: duckdb.DuckDBPyConnection) -> None:
        df = build_feature_matrix(mem_conn)
        expected_cols = [
            "n_playlists",
            "playlist_diversity",
            "fave_score",
            "year_normalized",
            "years_since_release",
            "duration_ms_normalized",
            "artist_enoa_top",
            "artist_enoa_left",
        ]
        for col in expected_cols:
            assert col in df.columns, f"Missing column: {col}"

    def test_build_empty_db(self) -> None:
        """Empty DB should return empty DataFrame gracefully."""
        conn = duckdb.connect(":memory:")
        conn.execute("""
            CREATE TABLE tracks (track_id VARCHAR PRIMARY KEY, track_name VARCHAR,
                release_date VARCHAR, year INTEGER, decade VARCHAR,
                popularity DOUBLE, first_genre VARCHAR, genre_cat VARCHAR);
            CREATE TABLE audio_features (track_id VARCHAR PRIMARY KEY,
                danceability DOUBLE, energy DOUBLE, loudness DOUBLE,
                speechiness DOUBLE, acousticness DOUBLE, instrumentalness DOUBLE,
                liveness DOUBLE, valence DOUBLE, tempo DOUBLE,
                duration_ms BIGINT, time_signature INTEGER,
                key INTEGER, mode INTEGER,
                key_labels VARCHAR, mode_labels VARCHAR, key_mode VARCHAR,
                features_source VARCHAR DEFAULT 'spotify');
            CREATE TABLE genre_map (first_genre VARCHAR PRIMARY KEY,
                gen_4 VARCHAR, gen_6 VARCHAR, gen_8 VARCHAR,
                my_genre VARCHAR, sub_genre VARCHAR,
                top DOUBLE, "left" DOUBLE, color VARCHAR);
            CREATE TABLE faves (track_id VARCHAR PRIMARY KEY, score DOUBLE);
            CREATE TABLE playlist_tracks (playlist_id VARCHAR, track_id VARCHAR,
                PRIMARY KEY (playlist_id, track_id));
            CREATE TABLE playlists (playlist_id VARCHAR PRIMARY KEY,
                playlist_name VARCHAR, gen_4 VARCHAR, gen_6 VARCHAR, gen_8 VARCHAR,
                top_genres VARCHAR, other_genres VARCHAR,
                include_in_refresh BOOLEAN, last_synced TIMESTAMP);
            CREATE TABLE track_artists (track_id VARCHAR, artist_id VARCHAR,
                PRIMARY KEY (track_id, artist_id));
            CREATE TABLE artists (artist_id VARCHAR PRIMARY KEY,
                artist_name VARCHAR, popularity DOUBLE, genres VARCHAR);
            CREATE TABLE genre_xy (first_genre VARCHAR PRIMARY KEY,
                top DOUBLE, "left" DOUBLE, color VARCHAR);
            CREATE TABLE track_embeddings (track_id VARCHAR PRIMARY KEY,
                embedding DOUBLE[64], model_version VARCHAR);
            CREATE OR REPLACE VIEW track_profile AS
            SELECT t.track_id, t.track_name, t.release_date, t.year, t.decade,
                t.popularity, t.first_genre, t.genre_cat,
                gm.gen_4, gm.gen_6, gm.gen_8, gm.my_genre, gm.sub_genre,
                gm.top, gm."left", gm.color,
                af.danceability, af.energy, af.loudness, af.speechiness,
                af.acousticness, af.instrumentalness, af.liveness, af.valence,
                af.tempo, af.duration_ms, af.time_signature, af.key, af.mode,
                af.key_labels, af.mode_labels, af.key_mode, af.features_source,
                COALESCE(f.score, 0.0) AS fave_score
            FROM tracks t
            LEFT JOIN audio_features af USING (track_id)
            LEFT JOIN genre_map gm ON t.first_genre = gm.first_genre
            LEFT JOIN faves f USING (track_id);
        """)
        df = build_feature_matrix(conn)
        assert len(df) == 0
        conn.close()
