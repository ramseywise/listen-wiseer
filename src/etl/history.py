"""
Import Spotify privacy-export listening history into the ``plays`` table.

Handles both export flavours found under LISTENING_HISTORY_PATH:
  - Extended streaming history: Streaming_History_Audio_*.json / endsong_*.json
    (full history, spotify:track URI, skip flag)
  - Account data: StreamingHistory_music_*.json / StreamingHistory<N>.json
    (last ~year, no URI, no skip flag)
Podcast / audiobook rows are dropped. Re-running is idempotent.

Run:
  PYTHONPATH=src uv run python -m etl.history
  make import-history
"""

import json
from pathlib import Path

import duckdb
import polars as pl

from etl.db import get_connection, init_schema
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

_EXTENDED_GLOBS = ("Streaming_History_Audio_*.json", "endsong_*.json")
_ACCOUNT_GLOBS = ("StreamingHistory_music_*.json", "StreamingHistory[0-9]*.json")

_EXTENDED_RAW = {
    "ts": pl.String,
    "ms_played": pl.Int64,
    "master_metadata_track_name": pl.String,
    "master_metadata_album_artist_name": pl.String,
    "master_metadata_album_album_name": pl.String,
    "spotify_track_uri": pl.String,
    "skipped": pl.Boolean,
    "reason_end": pl.String,
}
_ACCOUNT_RAW = {
    "endTime": pl.String,
    "artistName": pl.String,
    "trackName": pl.String,
    "msPlayed": pl.Int64,
}

PLAYS_COLUMNS = [
    "ts",
    "track_key",
    "spotify_id",
    "track_name",
    "artist_name",
    "album_name",
    "ms_played",
    "skipped",
    "reason_end",
]


def track_key(artist: str, title: str) -> str:
    """Join key across sources. Must match ``_track_key_expr``."""
    return f"{artist.strip().lower()}\t{title.strip().lower()}"


def _track_key_expr() -> pl.Expr:
    return pl.concat_str(
        [
            pl.col("artist_name").str.strip_chars().str.to_lowercase(),
            pl.col("track_name").str.strip_chars().str.to_lowercase(),
        ],
        separator="\t",
    ).alias("track_key")


def _read_records(path: Path, schema: dict) -> pl.DataFrame:
    records = json.loads(path.read_text(encoding="utf-8"))
    return pl.DataFrame(records if isinstance(records, list) else [records], schema=schema)


def _from_extended(raw: pl.DataFrame) -> pl.DataFrame:
    return (
        raw.filter(
            pl.col("spotify_track_uri").str.starts_with("spotify:track:")
            & pl.col("master_metadata_track_name").is_not_null()
        )
        .select(
            pl.col("ts").str.to_datetime("%Y-%m-%dT%H:%M:%SZ"),
            pl.col("spotify_track_uri").str.strip_prefix("spotify:track:").alias("spotify_id"),
            pl.col("master_metadata_track_name").alias("track_name"),
            pl.col("master_metadata_album_artist_name").alias("artist_name"),
            pl.col("master_metadata_album_album_name").alias("album_name"),
            pl.col("ms_played"),
            pl.col("skipped"),
            pl.col("reason_end"),
        )
        .with_columns(_track_key_expr())
    )


def _from_account(raw: pl.DataFrame) -> pl.DataFrame:
    return (
        raw.filter(pl.col("trackName").is_not_null() & pl.col("artistName").is_not_null())
        .select(
            pl.col("endTime").str.to_datetime("%Y-%m-%d %H:%M").alias("ts"),
            pl.lit(None, dtype=pl.String).alias("spotify_id"),
            pl.col("trackName").alias("track_name"),
            pl.col("artistName").alias("artist_name"),
            pl.lit(None, dtype=pl.String).alias("album_name"),
            pl.col("msPlayed").alias("ms_played"),
            pl.lit(None, dtype=pl.Boolean).alias("skipped"),
            pl.lit(None, dtype=pl.String).alias("reason_end"),
        )
        .with_columns(_track_key_expr())
    )


def _matching(base: Path, globs: tuple[str, ...]) -> list[Path]:
    return sorted({p for g in globs for p in base.glob(g)})


def load_plays(base: Path | None = None) -> pl.DataFrame:
    """All music plays under ``base`` in ``PLAYS_COLUMNS`` order, deduped on (ts, track_key).

    When both flavours are present the extended rows win on collisions — they carry
    spotify_id and skip info.
    """
    base = base or Path(settings.listening_history_path)
    frames = [
        _from_extended(_read_records(p, _EXTENDED_RAW)) for p in _matching(base, _EXTENDED_GLOBS)
    ]
    frames += [
        _from_account(_read_records(p, _ACCOUNT_RAW)) for p in _matching(base, _ACCOUNT_GLOBS)
    ]
    if not frames:
        log.warning("history.no_files", path=str(base))
        return pl.DataFrame(schema=dict.fromkeys(PLAYS_COLUMNS, pl.String))

    plays = (
        pl.concat([f.select(PLAYS_COLUMNS) for f in frames])
        .unique(subset=["ts", "track_key"], keep="first", maintain_order=True)
        .sort("ts")
    )
    log.info("history.loaded", n_plays=len(plays), n_files=len(frames))
    return plays


def import_history(conn: duckdb.DuckDBPyConnection, plays: pl.DataFrame | None = None) -> int:
    """Insert plays not already present. Returns the number of new rows."""
    plays = load_plays() if plays is None else plays
    if plays.is_empty():
        return 0
    before = conn.execute("SELECT count(*) FROM plays").fetchone()[0]  # type: ignore[index]
    conn.register("plays_df", plays)
    cols = ", ".join(PLAYS_COLUMNS)
    # cols is the PLAYS_COLUMNS constant — no user input interpolated
    conn.execute(f"INSERT OR IGNORE INTO plays ({cols}) SELECT {cols} FROM plays_df")  # noqa: S608
    conn.unregister("plays_df")
    after = conn.execute("SELECT count(*) FROM plays").fetchone()[0]  # type: ignore[index]
    log.info("history.imported", new_rows=after - before, total=after)
    return after - before


def main() -> None:
    conn = get_connection()
    init_schema(conn)
    import_history(conn)
    conn.close()


if __name__ == "__main__":
    main()
