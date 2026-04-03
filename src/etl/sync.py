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

from dataclasses import dataclass

import polars as pl

from etl.db import get_connection, init_schema
from spotify.client import SpotifyClient
from spotify.fetch import (
    fetch_artist_features,
    fetch_audio_features,
    fetch_my_playlists,
    fetch_playlist_tracks,
)
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
# Sync plan
# ---------------------------------------------------------------------------


@dataclass
class PlaylistSyncItem:
    """Per-playlist sync decision based on Spotify vs DB state."""

    playlist_id: str
    playlist_name: str
    spotify_track_count: int
    db_track_count: int
    is_new: bool
    include_in_refresh: bool

    @property
    def needs_sync(self) -> bool:
        return self.include_in_refresh and (
            self.is_new or self.spotify_track_count != self.db_track_count
        )

    @property
    def status(self) -> str:
        if not self.include_in_refresh:
            return "excluded"
        if self.is_new:
            return "new"
        if self.spotify_track_count != self.db_track_count:
            return "stale"
        return "current"


def plan_sync(conn, raw_playlists: list[dict]) -> list[PlaylistSyncItem]:
    """Compare Spotify playlist list against DB state. No writes, no extra API calls.

    Args:
        conn: DuckDB connection (read-only is fine).
        raw_playlists: Raw dicts from fetch_my_playlists (includes tracks.total).

    Returns:
        One PlaylistSyncItem per playlist, sorted by status then name.
    """
    rows = conn.execute(
        """
        SELECT playlist_id, COALESCE(include_in_refresh, TRUE)
        FROM playlists
    """
    ).fetchall()
    db_ids = {row[0] for row in rows}
    excluded_ids = {row[0] for row in rows if not row[1]}

    db_track_counts: dict[str, int] = dict(
        conn.execute(
            """
        SELECT playlist_id, COUNT(*) FROM playlist_tracks GROUP BY playlist_id
    """
        ).fetchall()
    )

    items = []
    for p in raw_playlists:
        pid = p["id"]
        items.append(
            PlaylistSyncItem(
                playlist_id=pid,
                playlist_name=p["name"],
                spotify_track_count=p.get("tracks", {}).get("total", 0),
                db_track_count=db_track_counts.get(pid, 0),
                is_new=pid not in db_ids,
                include_in_refresh=pid not in excluded_ids,
            )
        )

    by_status = {"new": 0, "stale": 0, "current": 0, "excluded": 0}
    for item in items:
        by_status[item.status] += 1

    log.info("sync.plan", total=len(items), **by_status)
    return sorted(items, key=lambda i: (i.status, i.playlist_name))


# ---------------------------------------------------------------------------
# Sync steps — each independently callable
# ---------------------------------------------------------------------------


def upsert_playlists(conn, items: list[PlaylistSyncItem]) -> None:
    """Register all playlists in DB. Upserts name; preserves existing include_in_refresh."""
    for item in items:
        conn.execute(
            """
            INSERT INTO playlists (playlist_id, playlist_name, include_in_refresh)
            VALUES (?, ?, TRUE)
            ON CONFLICT (playlist_id) DO UPDATE SET playlist_name = excluded.playlist_name
        """,
            [item.playlist_id, item.playlist_name],
        )
    log.info("sync.playlists.upserted", n=len(items))


def sync_tracks(conn, client: SpotifyClient, items: list[PlaylistSyncItem]) -> list:
    """Fetch tracks only for playlists where needs_sync=True.

    Upserts playlist_tracks, tracks, and track_artists for new track IDs only.

    Returns:
        All TrackFeatures fetched this run (only from synced playlists).
    """
    to_sync = [item for item in items if item.needs_sync]
    skipped = len(items) - len(to_sync)
    log.info("sync.tracks.start", to_sync=len(to_sync), skipped_unchanged=skipped)

    if not to_sync:
        return []

    existing_track_ids: set[str] = {
        row[0] for row in conn.execute("SELECT track_id FROM tracks").fetchall()
    }

    all_track_features = []
    new_track_ids: set[str] = set()

    for item in to_sync:
        tracks = fetch_playlist_tracks(client, item.playlist_id)
        all_track_features.extend(tracks)

        if tracks:
            pt = pl.DataFrame(
                [{"playlist_id": item.playlist_id, "track_id": t.id} for t in tracks]
            )
            conn.execute("INSERT OR IGNORE INTO playlist_tracks SELECT * FROM pt")

        new_here = [t for t in tracks if t.id not in existing_track_ids]
        new_track_ids.update(t.id for t in new_here)
        log.debug(
            "sync.tracks.playlist",
            playlist=item.playlist_name,
            total=len(tracks),
            new=len(new_here),
        )

    if new_track_ids:
        new_tracks = [t for t in all_track_features if t.id in new_track_ids]
        track_rows = pl.DataFrame(
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

        ta_rows = [
            {"track_id": t.id, "artist_id": aid}
            for t in new_tracks
            for aid in t.artist_ids
        ]
        if ta_rows:
            ta = pl.DataFrame(ta_rows).unique(["track_id", "artist_id"])
            conn.execute("INSERT OR IGNORE INTO track_artists SELECT * FROM ta")

    log.info(
        "sync.tracks.done",
        fetched=len(all_track_features),
        new_tracks=len(new_track_ids),
    )
    return all_track_features


def sync_audio_features(conn, client: SpotifyClient) -> int:
    """Fetch audio features for every track in DB that is missing them.

    Heals partial-sync gaps — safe to call at any time.

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

    total_tracks = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    log.info("sync.audio.start", total_tracks=total_tracks, missing=len(missing))

    if not missing:
        return 0

    audio = fetch_audio_features(client, missing)
    if not audio:
        return 0

    af_rows = pl.DataFrame(
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


def sync_artist_features(conn, client: SpotifyClient) -> int:
    """Fetch artist features for every artist in DB that is missing them.

    Heals partial-sync gaps — safe to call at any time.

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

    total_artist_refs = conn.execute(
        "SELECT COUNT(DISTINCT artist_id) FROM track_artists"
    ).fetchone()[0]
    log.info(
        "sync.artists.start", total_artists=total_artist_refs, missing=len(missing)
    )

    if not missing:
        return 0

    artists = fetch_artist_features(client, missing)
    if not artists:
        return 0

    ar_rows = pl.DataFrame(
        [
            {"artist_id": a.id, "popularity": a.popularity, "genres": str(a.genres)}
            for a in artists
        ]
    ).unique("artist_id")
    conn.execute("INSERT OR IGNORE INTO artists SELECT * FROM ar_rows")

    log.info("sync.artists.done", inserted=len(ar_rows))
    return len(ar_rows)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def sync(conn, client: SpotifyClient) -> None:
    """Full incremental sync: plan → playlists → tracks → audio → artists."""
    raw_playlists = fetch_my_playlists(client)
    items = plan_sync(conn, raw_playlists)

    upsert_playlists(conn, items)
    sync_tracks(conn, client, items)
    sync_audio_features(conn, client)
    sync_artist_features(conn, client)


def main() -> None:
    configure_logging()
    client = SpotifyClient()
    conn = get_connection()
    init_schema(conn)
    sync(conn, client)

    n = conn.execute("SELECT COUNT(*) FROM track_profile").fetchone()[0]
    log.info("sync.complete", track_profile_rows=n)
    conn.close()


if __name__ == "__main__":
    main()
