"""
Polars-based data loader.
Replaces pandas + hardcoded absolute paths in api/data/playlists.py and analysis/data.py.

All paths come from settings (env vars), not hardcoded filesystem locations.
Cache is written/read as Parquet for speed; falls back to CSV on first run.
"""

import json
from pathlib import Path

import polars as pl

from utils.config import settings
from utils.const import my_genres
from utils.logging import get_logger

log = get_logger(__name__)

# Key/mode integer → label maps (migrated from api/data/playlists.py)
_KEY_MAP = {
    0: "C",
    1: "Db",
    2: "D",
    3: "Eb",
    4: "E",
    5: "F",
    6: "F#",
    7: "G",
    8: "Ab",
    9: "A",
    10: "Bb",
    11: "B",
}
_MODE_MAP = {0: "Minor", 1: "Major"}


# ---------------------------------------------------------------------------
# Listening history
# ---------------------------------------------------------------------------


def load_listening_history() -> pl.DataFrame:
    """
    Load Spotify extended streaming history JSON exports.
    Files named StreamingHistory*.json or endsong_*.json under LISTENING_HISTORY_PATH.
    Returns one row per play event.
    """
    base = Path(settings.listening_history_path)
    files = sorted(base.glob("*.json"))
    if not files:
        log.warning("listening_history.empty", path=str(base))
        return pl.DataFrame()

    records: list[dict] = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        records.extend(data if isinstance(data, list) else [data])

    df = pl.DataFrame(records)

    # Normalise column names across export format versions
    rename = {
        "master_metadata_track_name": "track_name",
        "master_metadata_album_artist_name": "artist_name",
        "master_metadata_album_album_name": "album_name",
    }
    for old, new in rename.items():
        if old in df.columns:
            df = df.rename({old: new})

    log.info("listening_history.loaded", n_rows=len(df), n_files=len(files))
    return df


# ---------------------------------------------------------------------------
# Track / audio features cache
# ---------------------------------------------------------------------------


def load_track_features(csv_fallback: str | None = None) -> pl.DataFrame:
    """
    Load track audio features from Parquet cache.
    On first run, pass csv_fallback path to bootstrap the cache.
    """
    cache = Path(settings.track_features_cache)
    if cache.exists():
        df = pl.read_parquet(cache)
        log.info("track_features.loaded_from_cache", n_rows=len(df))
        return df

    if csv_fallback:
        df = pl.read_csv(csv_fallback)
        _save_parquet(df, cache)
        log.info("track_features.bootstrapped_from_csv", n_rows=len(df))
        return df

    log.warning("track_features.not_found", cache=str(cache))
    return pl.DataFrame()


def save_track_features(df: pl.DataFrame) -> None:
    _save_parquet(df, Path(settings.track_features_cache))
    log.info("track_features.saved", n_rows=len(df))


# ---------------------------------------------------------------------------
# Genre metadata cache
# ---------------------------------------------------------------------------


def load_genre_map(csv_fallback: str | None = None) -> pl.DataFrame:
    """
    Load genre map (first_genre → gen_4, gen_8, my_genre, ENOA x/y).
    Reads from Parquet cache; bootstraps from CSV on first run.
    """
    cache = Path(settings.genre_metadata_cache)
    if cache.exists():
        df = pl.read_parquet(cache)
        log.info("genre_map.loaded_from_cache", n_rows=len(df))
        return df

    if csv_fallback:
        df = pl.read_csv(csv_fallback)
        df = df.sort(["gen_4", "gen_8", "my_genre", "sub_genre", "first_genre"])
        _save_parquet(df, cache)
        log.info("genre_map.bootstrapped_from_csv", n_rows=len(df))
        return df

    log.warning("genre_map.not_found", cache=str(cache))
    return pl.DataFrame()


def save_genre_map(df: pl.DataFrame) -> None:
    _save_parquet(df, Path(settings.genre_metadata_cache))
    log.info("genre_map.saved", n_rows=len(df))


# ---------------------------------------------------------------------------
# Playlist CSV data (existing exported CSVs from v1)
# ---------------------------------------------------------------------------


def load_playlist_csvs(folder: str) -> pl.DataFrame:
    """
    Concatenate all playlist CSVs from a folder into one DataFrame.
    Used to migrate existing v1 data into Parquet cache.
    """
    folder_path = Path(folder)
    files = sorted(folder_path.glob("*.csv"))
    if not files:
        log.warning("playlist_csvs.empty", folder=folder)
        return pl.DataFrame()

    dfs = [pl.read_csv(f, infer_schema_length=1000) for f in files]
    df = pl.concat(dfs, how="diagonal")
    log.info("playlist_csvs.loaded", n_rows=len(df), n_files=len(files))
    return df


# ---------------------------------------------------------------------------
# Feature engineering (migrated from api/data/playlists.py)
# ---------------------------------------------------------------------------


def enrich_categorical_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Derive decade, key label, mode label, key_mode from raw audio feature integers.
    Replaces transform_cat_features() from api/data/playlists.py.
    """
    # Decade from release_date
    df = df.with_columns(
        pl.col("release_date")
        .str.slice(0, 4)
        .cast(pl.Int32, strict=False)
        .alias("year")
    ).with_columns(
        (pl.col("year") // 10 * 10)
        .cast(pl.Utf8)
        .str.replace(r"(\d+)", "${1}s")
        .alias("decade")
    )

    # Key label
    key_map_series = pl.Series("key_int", list(_KEY_MAP.keys()))
    key_label_series = pl.Series("key_label", list(_KEY_MAP.values()))
    df = df.with_columns(
        pl.col("key")
        .cast(pl.Int32, strict=False)
        .replace_strict(key_map_series, key_label_series, return_dtype=pl.Utf8)
        .alias("key_labels")
    )

    # Mode label
    mode_map_series = pl.Series("mode_int", list(_MODE_MAP.keys()))
    mode_label_series = pl.Series("mode_label", list(_MODE_MAP.values()))
    df = df.with_columns(
        pl.col("mode")
        .cast(pl.Int32, strict=False)
        .replace_strict(mode_map_series, mode_label_series, return_dtype=pl.Utf8)
        .alias("mode_labels")
    )

    # Combined key_mode
    df = df.with_columns(
        (pl.col("key_labels") + pl.lit(" ") + pl.col("mode_labels")).alias("key_mode")
    )

    return df


def tag_genre_categories(df: pl.DataFrame, genre_col: str = "genres") -> pl.DataFrame:
    """
    Add genre_cat column by searching genres string for known genre names.
    Replaces the loop in merge_artist_features() from api/data/playlists.py.
    """
    expr = pl.lit(None, dtype=pl.Utf8)
    for genre in my_genres:
        expr = (
            pl.when(pl.col(genre_col).str.contains(genre, literal=True))
            .then(pl.lit(genre))
            .otherwise(expr)
        )
    return df.with_columns(expr.alias("genre_cat"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _save_parquet(df: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)
