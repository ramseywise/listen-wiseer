"""
DuckDB connection and schema management.
DB file lives at data/listen_wiseer.db (gitignored).
"""

from pathlib import Path

import duckdb

from utils.logging import get_logger

log = get_logger(__name__)

DB_PATH = Path("data/listen_wiseer.db")

_DDL = """
-- Playlists dimension
CREATE TABLE IF NOT EXISTS playlists (
    playlist_id   VARCHAR PRIMARY KEY,
    playlist_name VARCHAR,
    gen_4         VARCHAR,
    gen_6         VARCHAR,
    gen_8         VARCHAR,
    top_genres    VARCHAR,
    other_genres  VARCHAR
);

-- Artists dimension
CREATE TABLE IF NOT EXISTS artists (
    artist_id   VARCHAR PRIMARY KEY,
    artist_name VARCHAR,
    popularity  DOUBLE,
    genres      VARCHAR   -- raw Spotify genres string / list
);
-- Migrate existing installs: add artist_name if missing
ALTER TABLE artists ADD COLUMN IF NOT EXISTS artist_name VARCHAR;

-- Genre taxonomy (your custom mapping) + ENOA map coordinates
CREATE TABLE IF NOT EXISTS genre_map (
    first_genre VARCHAR PRIMARY KEY,
    gen_4       VARCHAR,
    gen_6       VARCHAR,
    gen_8       VARCHAR,
    my_genre    VARCHAR,
    sub_genre   VARCHAR,
    top         DOUBLE,
    "left"      DOUBLE,
    color       VARCHAR
);
-- Migrate existing installs: add ENOA columns if missing
ALTER TABLE genre_map ADD COLUMN IF NOT EXISTS top DOUBLE;
ALTER TABLE genre_map ADD COLUMN IF NOT EXISTS "left" DOUBLE;
ALTER TABLE genre_map ADD COLUMN IF NOT EXISTS color VARCHAR;

-- Migrate existing installs: refresh flag and sync timestamp on playlists
ALTER TABLE playlists ADD COLUMN IF NOT EXISTS include_in_refresh BOOLEAN DEFAULT TRUE;
ALTER TABLE playlists ADD COLUMN IF NOT EXISTS last_synced TIMESTAMP;

-- Tracks dimension
CREATE TABLE IF NOT EXISTS tracks (
    track_id     VARCHAR PRIMARY KEY,
    track_name   VARCHAR,
    release_date VARCHAR,
    year         INTEGER,
    decade       VARCHAR,
    popularity   DOUBLE,
    first_genre  VARCHAR,
    genre_cat    VARCHAR
);

-- Audio features (one-to-one with tracks)
CREATE TABLE IF NOT EXISTS audio_features (
    track_id         VARCHAR PRIMARY KEY,
    danceability     DOUBLE,
    energy           DOUBLE,
    loudness         DOUBLE,
    speechiness      DOUBLE,
    acousticness     DOUBLE,
    instrumentalness DOUBLE,
    liveness         DOUBLE,
    valence          DOUBLE,
    tempo            DOUBLE,
    duration_ms      BIGINT,
    time_signature   INTEGER,
    key              INTEGER,
    mode             INTEGER,
    key_labels       VARCHAR,
    mode_labels      VARCHAR,
    key_mode         VARCHAR,
    features_source  VARCHAR DEFAULT 'spotify'
);
-- Migrate existing installs: add features_source if missing
ALTER TABLE audio_features ADD COLUMN IF NOT EXISTS features_source VARCHAR DEFAULT 'spotify';

-- ENOA genre map — all 6k+ genres with spatial coordinates (top/left) and color
-- Populated from data/archived/genres/genre_xy.csv at bootstrap
CREATE TABLE IF NOT EXISTS genre_xy (
    first_genre VARCHAR PRIMARY KEY,
    top         DOUBLE,
    "left"      DOUBLE,
    color       VARCHAR
);

-- Track2Vec embeddings (64d vectors from playlist co-occurrence)
CREATE TABLE IF NOT EXISTS track_embeddings (
    track_id       VARCHAR PRIMARY KEY,
    embedding      DOUBLE[64],
    model_version  VARCHAR DEFAULT 'track2vec_v1'
);

-- Track ↔ playlist (many-to-many)
CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id VARCHAR,
    track_id    VARCHAR,
    PRIMARY KEY (playlist_id, track_id)
);

-- Track ↔ artist (many-to-many, artist_ids stored as raw string in CSVs)
CREATE TABLE IF NOT EXISTS track_artists (
    track_id  VARCHAR,
    artist_id VARCHAR,
    PRIMARY KEY (track_id, artist_id)
);

-- Faves score (your personal rating)
CREATE TABLE IF NOT EXISTS faves (
    track_id VARCHAR PRIMARY KEY,
    score    DOUBLE
);

-- Enriched view used by agent / models
CREATE OR REPLACE VIEW track_profile AS
SELECT
    t.track_id,
    t.track_name,
    t.release_date,
    t.year,
    t.decade,
    t.popularity,
    t.first_genre,
    t.genre_cat,
    gm.gen_4,
    gm.gen_6,
    gm.gen_8,
    gm.my_genre,
    gm.sub_genre,
    gm.top,
    gm."left",
    gm.color,
    af.danceability,
    af.energy,
    af.loudness,
    af.speechiness,
    af.acousticness,
    af.instrumentalness,
    af.liveness,
    af.valence,
    af.tempo,
    af.duration_ms,
    af.time_signature,
    af.key,
    af.mode,
    af.key_labels,
    af.mode_labels,
    af.key_mode,
    COALESCE(f.score, 0.0) AS fave_score
FROM tracks t
LEFT JOIN audio_features af USING (track_id)
LEFT JOIN genre_map gm ON t.first_genre = gm.first_genre
LEFT JOIN faves f USING (track_id);
"""


def get_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Return a connection to the project DuckDB file."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DB_PATH), read_only=read_only)
    log.debug("db.connected", path=str(DB_PATH), read_only=read_only)
    return conn


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all tables and the track_profile view (idempotent)."""
    conn.execute(_DDL)
    log.info("db.schema_initialized")
