"""
Incremental Spotify → DuckDB sync.

Each step filters against existing DB records before calling the API, so re-running
is cheap and partial-sync failures are automatically healed on the next run.

Functions are individually callable from notebooks for step-by-step control.

Run:
  PYTHONPATH=src uv run python -m etl.sync
  make data-sync
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import polars as pl

from etl.db import get_connection, init_schema
from etl.lastfm import fetch_genres_for_tracks
from paths import PLAYLIST_CONFIG_PATH
from spotify.client import SpotifyClient
from spotify.fetch import (
    fetch_artist_features,
    fetch_audio_features,
    fetch_my_playlists,
    fetch_playlist_tracks,
)
from utils.config import settings
from utils.logging import configure_logging, get_logger

log = get_logger(__name__)

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
# Playlist config
# ---------------------------------------------------------------------------

_VALID_STATUSES = frozenset({"active", "archived", "excluded"})


def load_playlist_config() -> dict[str, str]:
    """Return mapping of playlist_name → status from playlist_status.toml.

    Any playlist not listed defaults to 'excluded'.
    Logs a warning if the config file is missing.
    """
    if not PLAYLIST_CONFIG_PATH.exists():
        log.warning("sync.config.missing", path=str(PLAYLIST_CONFIG_PATH))
        return {}
    with PLAYLIST_CONFIG_PATH.open("rb") as fh:
        raw = tomllib.load(fh)
    playlists = raw.get("playlists", {})
    result: dict[str, str] = {}
    for name, attrs in playlists.items():
        status = attrs.get("status", "excluded")
        if status not in _VALID_STATUSES:
            log.warning("sync.config.invalid_status", playlist=name, status=status)
            status = "excluded"
        result[name] = status
    log.info("sync.config.loaded", n=len(result), path=str(PLAYLIST_CONFIG_PATH))
    return result


# ---------------------------------------------------------------------------
# Sync plan
# ---------------------------------------------------------------------------


_SYNC_INTERVAL = timedelta(hours=23)


@dataclass
class PlaylistSyncItem:
    """Per-playlist sync decision based on Spotify vs DB state."""

    playlist_id: str
    playlist_name: str
    spotify_track_count: int
    db_track_count: int
    is_new: bool
    playlist_status: str  # 'active' | 'archived' | 'excluded'
    last_synced: datetime | None = None

    @property
    def needs_sync(self) -> bool:
        if self.playlist_status != "active":
            return False
        if self.is_new or self.spotify_track_count != self.db_track_count:
            # Still rate-limit: skip if synced recently regardless of count change
            if self.last_synced is not None:
                age = datetime.now(UTC) - self.last_synced.replace(tzinfo=UTC)
                if age < _SYNC_INTERVAL:
                    return False
            return True
        return False

    @property
    def sync_status(self) -> str:
        if self.playlist_status != "active":
            return self.playlist_status  # 'archived' or 'excluded'
        if self.is_new:
            return "new"
        if self.spotify_track_count != self.db_track_count:
            return "stale"
        return "current"


def plan_sync(conn, raw_playlists: list[dict]) -> list[PlaylistSyncItem]:
    """Compare Spotify playlist list against DB state. No writes, no extra API calls.

    Status resolution order:
      1. playlist_status.toml (by name) — authoritative
      2. DB status column — used if name not in config
      3. Default 'excluded' for any playlist not previously seen

    Args:
        conn: DuckDB connection (read-only is fine).
        raw_playlists: Raw dicts from fetch_my_playlists (includes tracks.total).

    Returns:
        One PlaylistSyncItem per playlist, sorted by sync_status then name.
    """
    name_config = load_playlist_config()

    rows = conn.execute(
        """
        SELECT playlist_id, playlist_name, COALESCE(status, 'excluded'), last_synced
        FROM playlists
    """
    ).fetchall()
    db_ids = {row[0] for row in rows}
    db_status_map: dict[str, str] = {row[0]: row[2] for row in rows}
    last_synced_map: dict[str, datetime | None] = {row[0]: row[3] for row in rows}

    db_track_counts: dict[str, int] = dict(
        conn.execute(
            """
        SELECT playlist_id, COUNT(*) FROM playlist_tracks WHERE removed_at IS NULL
        GROUP BY playlist_id
    """
        ).fetchall()
    )

    items = []
    for p in raw_playlists:
        pid = p["id"]
        name = p["name"]
        # Config by name takes priority; fall back to DB status; new playlists default excluded
        if name in name_config:
            pstatus = name_config[name]
        elif pid in db_status_map:
            pstatus = db_status_map[pid]
        else:
            pstatus = "excluded"

        items.append(
            PlaylistSyncItem(
                playlist_id=pid,
                playlist_name=name,
                spotify_track_count=p.get("tracks", {}).get("total", 0),
                db_track_count=db_track_counts.get(pid, 0),
                is_new=pid not in db_ids,
                playlist_status=pstatus,
                last_synced=last_synced_map.get(pid),
            )
        )

    by_status: dict[str, int] = {"new": 0, "stale": 0, "current": 0, "archived": 0, "excluded": 0}
    for item in items:
        key = item.sync_status
        by_status[key] = by_status.get(key, 0) + 1

    log.info("sync.plan", total=len(items), **by_status)
    return sorted(items, key=lambda i: (i.sync_status, i.playlist_name))


# ---------------------------------------------------------------------------
# Sync steps — each independently callable
# ---------------------------------------------------------------------------


def upsert_playlists(conn, items: list[PlaylistSyncItem]) -> None:
    """Register all playlists in DB. Upserts name, status, and last_synced."""
    now = datetime.now(UTC)
    new_count = 0
    for item in items:
        synced_at = now if item.needs_sync else None
        conn.execute(
            """
            INSERT INTO playlists (playlist_id, playlist_name, status, last_synced)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (playlist_id) DO UPDATE SET
                playlist_name = excluded.playlist_name,
                status        = excluded.status,
                last_synced   = CASE WHEN excluded.last_synced IS NOT NULL
                                     THEN excluded.last_synced
                                     ELSE playlists.last_synced END
        """,
            [item.playlist_id, item.playlist_name, item.playlist_status, synced_at],
        )
        if item.is_new:
            new_count += 1
    log.info("sync.playlists.upserted", n=len(items), new_excluded=new_count)


def sync_tracks(
    conn,
    client: SpotifyClient,
    items: list[PlaylistSyncItem],
    max_playlists: int | None = None,
    max_tracks: int | None = None,
) -> list:
    """Fetch tracks only for playlists where needs_sync=True.

    Upserts playlist_tracks, tracks, and track_artists for new track IDs only.

    Args:
        max_playlists: Cap number of playlists synced this run (None = no limit).
        max_tracks: Cap total tracks fetched across all playlists (None = no limit).

    Returns:
        All TrackFeatures fetched this run (only from synced playlists).
    """
    to_sync = [item for item in items if item.needs_sync]
    if max_playlists is not None:
        to_sync = to_sync[:max_playlists]
    skipped = len(items) - len(to_sync)
    log.info(
        "sync.tracks.start",
        to_sync=len(to_sync),
        skipped_unchanged=skipped,
        max_playlists=max_playlists,
        max_tracks=max_tracks,
    )

    if not to_sync:
        return []

    existing_track_ids: set[str] = {
        row[0] for row in conn.execute("SELECT track_id FROM tracks").fetchall()
    }

    all_track_features = []
    new_track_ids: set[str] = set()
    now = datetime.now(UTC)

    for item in to_sync:
        if max_tracks is not None and len(all_track_features) >= max_tracks:
            log.info("sync.tracks.limit_reached", max_tracks=max_tracks)
            break
        tracks = fetch_playlist_tracks(client, item.playlist_id)
        if max_tracks is not None:
            remaining = max_tracks - len(all_track_features)
            tracks = tracks[:remaining]
        all_track_features.extend(tracks)

        spotify_ids: set[str] = {t.id for t in tracks}

        if tracks:
            # Upsert active members — clear removed_at if track returned to playlist
            pt = pl.DataFrame(  # noqa: F841
                [{"playlist_id": item.playlist_id, "track_id": t.id} for t in tracks]
            )
            conn.execute(
                """
                INSERT INTO playlist_tracks (playlist_id, track_id, removed_at)
                SELECT playlist_id, track_id, NULL FROM pt
                ON CONFLICT (playlist_id, track_id) DO UPDATE SET removed_at = NULL
                """
            )

        # Mark tracks no longer on Spotify as removed
        active_db_ids: set[str] = {
            row[0]
            for row in conn.execute(
                "SELECT track_id FROM playlist_tracks WHERE playlist_id = ? AND removed_at IS NULL",
                [item.playlist_id],
            ).fetchall()
        }
        removed_ids = active_db_ids - spotify_ids
        if removed_ids:
            for tid in removed_ids:
                conn.execute(
                    "UPDATE playlist_tracks SET removed_at = ? WHERE playlist_id = ? AND track_id = ?",
                    [now, item.playlist_id, tid],
                )
            log.info(
                "sync.tracks.removed",
                playlist=item.playlist_name,
                n_removed=len(removed_ids),
            )

        new_here = [t for t in tracks if t.id not in existing_track_ids]
        new_track_ids.update(t.id for t in new_here)
        log.debug(
            "sync.tracks.playlist",
            playlist=item.playlist_name,
            total=len(tracks),
            new=len(new_here),
            removed=len(removed_ids) if removed_ids else 0,
        )

    if new_track_ids:
        new_tracks = [t for t in all_track_features if t.id in new_track_ids]
        track_rows = pl.DataFrame(  # noqa: F841
            [
                {
                    "track_id": t.id,
                    "track_name": t.name,
                    "release_date": t.release_date,
                    "year": int(t.release_date[:4])
                    if t.release_date and len(t.release_date) >= 4
                    else None,
                    "decade": None,
                    "popularity": None,
                    "first_genre": None,
                    "genre_cat": None,
                }
                for t in new_tracks
            ]
        ).unique("track_id")
        conn.execute("INSERT OR IGNORE INTO tracks SELECT * FROM track_rows")

        ta_rows = [{"track_id": t.id, "artist_id": aid} for t in new_tracks for aid in t.artist_ids]
        if ta_rows:
            ta = pl.DataFrame(ta_rows).unique(["track_id", "artist_id"])  # noqa: F841
            conn.execute("INSERT OR IGNORE INTO track_artists SELECT * FROM ta")

        # Upsert artist names (artist_names aligns positionally with artist_ids)
        name_rows = [
            {"artist_id": aid, "artist_name": name}
            for t in new_tracks
            for aid, name in zip(t.artist_ids, t.artist_names, strict=False)
            if name
        ]
        if name_rows:
            an = pl.DataFrame(name_rows).unique("artist_id")  # noqa: F841
            conn.execute(
                """
                INSERT INTO artists (artist_id, artist_name)
                SELECT artist_id, artist_name FROM an
                ON CONFLICT (artist_id) DO UPDATE SET
                    artist_name = CASE WHEN artists.artist_name IS NULL
                                       THEN excluded.artist_name
                                       ELSE artists.artist_name END
                """
            )

    log.info(
        "sync.tracks.done",
        fetched=len(all_track_features),
        new_tracks=len(new_track_ids),
    )
    return all_track_features


def sync_audio_features(conn, client: SpotifyClient, limit: int | None = None) -> int:
    """Fetch audio features for every track in DB that is missing them.

    Heals partial-sync gaps — safe to call at any time.

    Args:
        limit: Cap number of tracks to fetch audio features for (None = no limit).

    Returns:
        Number of new audio feature rows inserted.
    """
    missing: list[str] = [
        row[0]
        for row in conn.execute(
            """
            SELECT t.track_id FROM tracks t
            LEFT JOIN audio_features af USING (track_id)
            WHERE af.track_id IS NULL
        """
        ).fetchall()
    ]
    if limit is not None:
        missing = missing[:limit]

    total_tracks = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    log.info("sync.audio.start", total_tracks=total_tracks, missing=len(missing), limit=limit)

    if not missing:
        return 0

    audio = fetch_audio_features(client, missing)
    if not audio:
        return 0

    af_rows = pl.DataFrame(  # noqa: F841
        [
            {
                "track_id": a.id,
                "danceability": a.danceability,
                "energy": a.energy,
                "loudness": a.loudness,
                "speechiness": a.speechiness,
                "acousticness": a.acousticness,
                "instrumentalness": a.instrumentalness,
                "liveness": a.liveness,
                "valence": a.valence,
                "tempo": a.tempo,
                "duration_ms": a.duration_ms,
                "time_signature": a.time_signature,
                "key": a.key,
                "mode": a.mode,
                "key_labels": _KEY_MAP.get(a.key, ""),
                "mode_labels": _MODE_MAP.get(a.mode, ""),
                "key_mode": f"{_KEY_MAP.get(a.key, '')} {_MODE_MAP.get(a.mode, '')}",
            }
            for a in audio
        ]
    ).unique("track_id")
    conn.execute("INSERT OR IGNORE INTO audio_features SELECT * FROM af_rows")

    log.info("sync.audio.done", inserted=len(af_rows))
    return len(af_rows)


def sync_artist_features(conn, client: SpotifyClient, limit: int | None = None) -> int:
    """Fetch artist features for every artist in DB that is missing them.

    Heals partial-sync gaps — safe to call at any time.

    Args:
        limit: Cap number of artists to fetch features for (None = no limit).

    Returns:
        Number of new artist rows inserted.
    """
    missing: list[str] = [
        row[0]
        for row in conn.execute(
            """
            SELECT ta.artist_id FROM track_artists ta
            LEFT JOIN artists a USING (artist_id)
            WHERE a.artist_id IS NULL
        """
        ).fetchall()
    ]
    if limit is not None:
        missing = missing[:limit]

    total_artist_refs = conn.execute(
        "SELECT COUNT(DISTINCT artist_id) FROM track_artists"
    ).fetchone()[0]
    log.info(
        "sync.artists.start", total_artists=total_artist_refs, missing=len(missing), limit=limit
    )

    if not missing:
        return 0

    artists = fetch_artist_features(client, missing)
    if not artists:
        return 0

    ar_rows = pl.DataFrame(  # noqa: F841
        [{"artist_id": a.id, "popularity": a.popularity, "genres": str(a.genres)} for a in artists]
    ).unique("artist_id")
    conn.execute("INSERT OR IGNORE INTO artists SELECT * FROM ar_rows")

    log.info("sync.artists.done", inserted=len(ar_rows))
    return len(ar_rows)


def sync_lastfm_genres(conn, limit: int | None = None) -> int:
    """Fetch Last.fm genre tags for tracks missing first_genre.

    Matches returned tags against the genre_xy table (6k+ ENOA genres).
    Writes first_genre to tracks and inserts a stub audio_features row
    flagged features_source='lastfm' so feature engineering can derive
    proxies from ENOA coordinates.

    Args:
        conn: DuckDB connection (read-write).
        limit: Cap number of tracks to process this run (None = no limit).

    Returns:
        Number of tracks where a genre match was found and written.
    """
    api_key = settings.last_fm_api_key
    if not api_key:
        log.warning("sync.lastfm.skip", reason="LAST_FM_API_KEY not set")
        return 0

    # Load genre_xy set for tag matching
    genre_xy_rows = conn.execute("SELECT first_genre FROM genre_xy").fetchall()
    genre_xy_set: set[str] = {row[0].lower() for row in genre_xy_rows}
    if not genre_xy_set:
        log.warning("sync.lastfm.skip", reason="genre_xy table is empty — run bootstrap first")
        return 0

    track_rows = conn.execute(
        """
        SELECT
            t.track_id,
            t.track_name,
            COALESCE(
                (SELECT a.artist_name
                 FROM track_artists ta
                 JOIN artists a USING (artist_id)
                 WHERE ta.track_id = t.track_id
                   AND a.artist_name IS NOT NULL
                 LIMIT 1),
                ''
            ) AS primary_artist_name
        FROM tracks t
        WHERE t.first_genre IS NULL
        ORDER BY t.track_id
        """
    ).fetchall()

    if limit is not None:
        track_rows = track_rows[:limit]

    total_missing = conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE first_genre IS NULL"
    ).fetchone()[0]
    log.info(
        "sync.lastfm.start", total_missing=total_missing, processing=len(track_rows), limit=limit
    )

    if not track_rows:
        return 0

    tracks_for_fetch = [
        {
            "track_id": row[0],
            "track_name": row[1],
            "artist_name": row[2] if row[2] else row[1],
        }
        for row in track_rows
    ]

    genre_map = fetch_genres_for_tracks(tracks_for_fetch, api_key, genre_xy_set)

    matched = 0
    for track_id, genre in genre_map.items():
        if genre is None:
            continue
        # Write first_genre to tracks
        conn.execute(
            "UPDATE tracks SET first_genre = ? WHERE track_id = ?",
            [genre, track_id],
        )
        # Insert stub audio_features row flagged as lastfm so feature engineering
        # can derive proxies from ENOA coordinates (numeric fields left NULL)
        conn.execute(
            """
            INSERT OR IGNORE INTO audio_features (track_id, features_source)
            VALUES (?, 'lastfm')
            """,
            [track_id],
        )
        matched += 1

    log.info("sync.lastfm.done", processed=len(track_rows), matched=matched)
    return matched


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def sync_genre_profiles(conn) -> None:
    """Refresh track_genre, artist_genre, and playlist_genre from current DB state.

    Runs after lastfm genre sync so newly tagged tracks get genre profiles assigned.
    Uses genre_map (manual taxonomy) and genre_xy (ENOA coordinates) as lookup sources.
    Tracks with no match are written with genre_source='unknown' for later model inference.
    """
    from etl.genre_tables import (
        populate_artist_genre,
        populate_playlist_genre,
        populate_track_genre,
    )

    populate_track_genre(conn)
    populate_artist_genre(conn)
    populate_playlist_genre(conn)
    log.info("sync.genre_profiles.done")


def sync(
    conn,
    client: SpotifyClient,
    max_playlists: int | None = None,
    max_tracks: int | None = None,
    audio_limit: int | None = None,
    artist_limit: int | None = None,
    lastfm_limit: int | None = None,
) -> None:
    """Full incremental sync: plan → playlists → tracks → audio → artists → lastfm → genre profiles.

    Args:
        max_playlists: Cap playlists synced this run.
        max_tracks: Cap total tracks fetched across all playlists.
        audio_limit: Cap tracks to fetch audio features for.
        artist_limit: Cap artists to fetch features for.
        lastfm_limit: Cap tracks to fetch Last.fm genre tags for (None = no limit).
    """
    raw_playlists = fetch_my_playlists(client)
    items = plan_sync(conn, raw_playlists)

    upsert_playlists(conn, items)
    sync_tracks(conn, client, items, max_playlists=max_playlists, max_tracks=max_tracks)
    sync_audio_features(conn, client, limit=audio_limit)
    sync_artist_features(conn, client, limit=artist_limit)
    sync_lastfm_genres(conn, limit=lastfm_limit)
    sync_genre_profiles(conn)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Incremental Spotify → DuckDB sync")
    parser.add_argument(
        "--playlists",
        type=int,
        default=None,
        metavar="N",
        help="Max playlists to sync tracks for (default: no limit)",
    )
    parser.add_argument(
        "--tracks",
        type=int,
        default=None,
        metavar="N",
        help="Max total tracks to fetch (default: no limit)",
    )
    parser.add_argument(
        "--audio-limit",
        type=int,
        default=None,
        metavar="N",
        help="Max tracks to fetch audio features for (default: no limit)",
    )
    parser.add_argument(
        "--artist-limit",
        type=int,
        default=None,
        metavar="N",
        help="Max artists to fetch features for (default: no limit)",
    )
    parser.add_argument(
        "--lastfm-limit",
        type=int,
        default=None,
        metavar="N",
        help="Max tracks to fetch Last.fm genre tags for (default: no limit)",
    )
    args = parser.parse_args()

    configure_logging()
    client = SpotifyClient()
    conn = get_connection()
    init_schema(conn)
    sync(
        conn,
        client,
        max_playlists=args.playlists,
        max_tracks=args.tracks,
        audio_limit=args.audio_limit,
        artist_limit=args.artist_limit,
        lastfm_limit=args.lastfm_limit,
    )

    n = conn.execute("SELECT COUNT(*) FROM track_profile").fetchone()[0]
    log.info("sync.complete", track_profile_rows=n)
    conn.close()


if __name__ == "__main__":
    main()
