"""
Local playlists in DuckDB — the Spotify-free replacement for create_playlist.
Export as JSPF (importable into ListenBrainz and most players).
"""

import uuid
from datetime import datetime

import duckdb

from sources.schemas import TrackRef
from utils.logging import get_logger

log = get_logger(__name__)


def save_playlist(
    conn: duckdb.DuckDBPyConnection,
    name: str,
    tracks: list[TrackRef],
    description: str = "",
) -> str:
    """Store a new playlist and return its id. Names need not be unique."""
    pid = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO local_playlists (id, name, description, created_at) VALUES (?, ?, ?, ?)",
        [pid, name, description, datetime.now()],
    )
    if tracks:
        conn.executemany(
            "INSERT INTO local_playlist_tracks"
            " (playlist_id, position, artist_name, track_name, mbid) VALUES (?, ?, ?, ?, ?)",
            [[pid, i, t.artist, t.title, t.mbid] for i, t in enumerate(tracks)],
        )
    log.info("playlist.saved", id=pid, name=name, n_tracks=len(tracks))
    return pid


def list_playlists(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT p.id, p.name, p.description, p.created_at, count(t.position)
        FROM local_playlists p
        LEFT JOIN local_playlist_tracks t ON t.playlist_id = p.id
        GROUP BY ALL
        ORDER BY p.created_at DESC
        """
    ).fetchall()
    keys = ("id", "name", "description", "created_at", "n_tracks")
    return [dict(zip(keys, r, strict=True)) for r in rows]


def get_tracks(conn: duckdb.DuckDBPyConnection, playlist_id: str) -> list[TrackRef]:
    rows = conn.execute(
        "SELECT artist_name, track_name, mbid FROM local_playlist_tracks"
        " WHERE playlist_id = ? ORDER BY position",
        [playlist_id],
    ).fetchall()
    return [TrackRef(artist=a, title=t, mbid=m or "") for a, t, m in rows]


def to_jspf(name: str, tracks: list[TrackRef], description: str = "") -> dict:
    out = []
    for t in tracks:
        item: dict = {"title": t.title, "creator": t.artist}
        if t.mbid:
            item["identifier"] = [f"https://musicbrainz.org/recording/{t.mbid}"]
        out.append(item)
    return {"playlist": {"title": name, "annotation": description, "track": out}}
