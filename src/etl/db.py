"""
DuckDB connection and schema management.
DB file lives at infrastructure/db/listen_wiseer.db (tracked via Git LFS).
"""

import duckdb

from paths import DB_PATH
from utils.logging import get_logger

log = get_logger(__name__)

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
-- Playlist sync status: 'active' | 'archived' | 'excluded'
ALTER TABLE playlists ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'excluded';

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
-- removed_at: set when a track is no longer in the Spotify playlist; NULL = currently active member
CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id VARCHAR,
    track_id    VARCHAR,
    removed_at  TIMESTAMP,
    PRIMARY KEY (playlist_id, track_id)
);
-- Migrate existing installs: add removed_at if missing
ALTER TABLE playlist_tracks ADD COLUMN IF NOT EXISTS removed_at TIMESTAMP;

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

-- Per-track genre assignment (updatable; source of truth for genre profiles)
CREATE TABLE IF NOT EXISTS track_genre (
    track_id     VARCHAR PRIMARY KEY,
    first_genre  VARCHAR,
    gen_4        VARCHAR,
    gen_6        VARCHAR,
    gen_8        VARCHAR,
    my_genre     VARCHAR,
    sub_genre    VARCHAR,
    top          DOUBLE,
    "left"       DOUBLE,
    color        VARCHAR,
    genre_source VARCHAR  -- 'manual' | 'model' | 'lookup'
);

-- Per-artist genre profile (derived from track_genre via track_artists)
CREATE TABLE IF NOT EXISTS artist_genre (
    artist_id       VARCHAR PRIMARY KEY,
    gen_4           VARCHAR,
    gen_6           VARCHAR,
    gen_8           VARCHAR,
    my_genre        VARCHAR,
    top             DOUBLE,
    "left"          DOUBLE,
    dominant_genres VARCHAR,  -- JSON array of top first_genres by count
    track_count     INTEGER
);

-- Per-playlist genre profile (derived from track_genre via playlist_tracks)
CREATE TABLE IF NOT EXISTS playlist_genre (
    playlist_id  VARCHAR PRIMARY KEY,
    gen_4        VARCHAR,
    gen_6        VARCHAR,
    gen_8        VARCHAR,
    top_genres   VARCHAR,  -- JSON array (top 5 by count)
    other_genres VARCHAR,  -- JSON array (remaining)
    top          DOUBLE,
    "left"       DOUBLE,
    track_count  INTEGER
);

-- External training corpus (595k Spotify tracks with y_target label)
CREATE TABLE IF NOT EXISTS external_tracks (
    track_id         VARCHAR PRIMARY KEY,
    track_name       VARCHAR,
    artist_names     VARCHAR,
    popularity       DOUBLE,
    release_date     VARCHAR,
    year             INTEGER,
    decade           VARCHAR,
    first_genre      VARCHAR,
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
    top              DOUBLE,
    "left"           DOUBLE,
    color            VARCHAR,
    y_target         VARCHAR
);

-- RAG chunks for artist/genre context (Phase 5a)
-- Embeddings are 384-dim float arrays from all-MiniLM-L6-v2
CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id    VARCHAR PRIMARY KEY,
    subject     VARCHAR NOT NULL,
    section     VARCHAR DEFAULT 'bio',
    source_url  VARCHAR DEFAULT '',
    text        VARCHAR NOT NULL,
    embedding   FLOAT[384],
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Enriched view used by agent / models
-- genre columns sourced from track_genre (falls back to genre_map for coverage)
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
    COALESCE(tg.gen_4,  gm.gen_4)     AS gen_4,
    COALESCE(tg.gen_6,  gm.gen_6)     AS gen_6,
    COALESCE(tg.gen_8,  gm.gen_8)     AS gen_8,
    COALESCE(tg.my_genre, gm.my_genre) AS my_genre,
    COALESCE(tg.sub_genre, gm.sub_genre) AS sub_genre,
    COALESCE(tg.top,   gm.top)        AS top,
    COALESCE(tg."left", gm."left")    AS "left",
    COALESCE(tg.color,  gm.color)     AS color,
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
    af.features_source,
    COALESCE(f.score, 0.0) AS fave_score
FROM tracks t
LEFT JOIN audio_features af USING (track_id)
LEFT JOIN track_genre tg USING (track_id)
LEFT JOIN genre_map gm ON t.first_genre = gm.first_genre
LEFT JOIN faves f USING (track_id);
"""


def get_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Return a connection to the project DuckDB file."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = duckdb.connect(str(DB_PATH), read_only=read_only)
    except duckdb.IOException:
        # File exists but is not a valid DuckDB database (e.g. a Git LFS pointer).
        # Delete it and create a fresh database.
        if DB_PATH.exists() and DB_PATH.read_bytes()[:8] != b"DUCK\x00\x00\x00\x00":
            log.warning("db.invalid_file.replaced", path=str(DB_PATH))
            DB_PATH.unlink()
            conn = duckdb.connect(str(DB_PATH), read_only=read_only)
        else:
            raise
    log.debug("db.connected", path=str(DB_PATH), read_only=read_only)
    return conn


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all tables and the track_profile view (idempotent)."""
    conn.execute(_DDL)
    log.info("db.schema_initialized")
