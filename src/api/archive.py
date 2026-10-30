"""Archived Spotify playlists (frozen DuckDB tables ``playlists`` / ``playlist_tracks`` /
``tracks`` / ``track_artists`` / ``artists``) — read-only browse, plus "copy to library":
match each track to a Navidrome song and create a real playlist from the hits.

Tracks keep their archive order (``playlist_tracks`` insertion order) and only current
members (``removed_at IS NULL``) are listed.
"""

import asyncio
from collections.abc import Callable
from typing import TypeVar

import duckdb
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from api.deps import Db, DbConnect, Subsonic
from library.match import DuckDBMatchCache
from library.to_navidrome import song_ids_for
from sources.schemas import TrackRef
from sources.subsonic import Playlist
from utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/archive", tags=["archive"])

T = TypeVar("T")


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ArchivePlaylistSummary(_Model):
    id: str
    name: str
    track_count: int


class ArchiveTrack(_Model):
    artist: str
    title: str
    album: str | None = None
    mbid: str | None = None


class ArchivePlaylist(_Model):
    id: str
    name: str
    tracks: list[ArchiveTrack]


class CopyRequest(_Model):
    name: str | None = Field(None, min_length=1)


class CopyResult(_Model):
    playlist: Playlist
    unmatched: list[ArchiveTrack]


_NAME = "coalesce(nullif(trim(p.playlist_name), ''), 'Untitled')"

_LIST_SQL = f"""
SELECT p.playlist_id, {_NAME} AS name,
       count(pt.track_id) FILTER (WHERE pt.removed_at IS NULL) AS n
FROM playlists p
LEFT JOIN playlist_tracks pt USING (playlist_id)
GROUP BY p.playlist_id, p.playlist_name
ORDER BY lower(name), p.playlist_id
"""  # noqa: S608 — _NAME is a constant

_NAME_SQL = f"SELECT {_NAME} FROM playlists p WHERE p.playlist_id = ?"  # noqa: S608

# Artists in track_artists insertion order = Spotify's credit order (primary first).
_TRACKS_SQL = """
WITH members AS (
    SELECT pt.track_id, pt.rowid AS pos
    FROM playlist_tracks pt
    WHERE pt.playlist_id = ? AND pt.removed_at IS NULL
),
credits AS (
    SELECT ta.track_id, string_agg(a.artist_name, ', ' ORDER BY ta.rowid) AS artist
    FROM track_artists ta
    JOIN artists a USING (artist_id)
    WHERE ta.track_id IN (SELECT track_id FROM members) AND a.artist_name IS NOT NULL
    GROUP BY ta.track_id
),
mbids AS (
    SELECT spotify_id, any_value(mbid) AS mbid
    FROM track_xref
    WHERE mbid IS NOT NULL AND spotify_id IN (SELECT track_id FROM members)
    GROUP BY spotify_id
)
SELECT coalesce(c.artist, ''), trim(t.track_name), x.mbid
FROM members m
JOIN tracks t USING (track_id)
LEFT JOIN credits c USING (track_id)
LEFT JOIN mbids x ON x.spotify_id = m.track_id
ORDER BY m.pos
"""


def _query(connect: DbConnect, work: Callable[[duckdb.DuckDBPyConnection], T]) -> T:
    # Read-write like every other connection in this process: DuckDB refuses a read-only
    # connection to a file already open read-write here (scrobbles write ``plays``).
    conn = connect()
    try:
        return work(conn)
    finally:
        conn.close()


async def _run(connect: DbConnect, work: Callable[[duckdb.DuckDBPyConnection], T]) -> T:
    try:
        return await asyncio.to_thread(_query, connect, work)
    except duckdb.IOException as exc:  # another process holds the DB lock
        log.warning("api.archive.db_unavailable", error=str(exc))
        raise HTTPException(503, "Database is busy (another process holds the lock)") from exc


def list_archive(conn: duckdb.DuckDBPyConnection) -> list[ArchivePlaylistSummary]:
    rows = conn.execute(_LIST_SQL).fetchall()
    return [ArchivePlaylistSummary(id=i, name=n, track_count=c) for i, n, c in rows]


def load_archive_playlist(
    conn: duckdb.DuckDBPyConnection, playlist_id: str
) -> ArchivePlaylist | None:
    found = conn.execute(_NAME_SQL, [playlist_id]).fetchall()
    if not found:
        return None
    rows = conn.execute(_TRACKS_SQL, [playlist_id]).fetchall()
    tracks = [ArchiveTrack(artist=a, title=t, mbid=m or None) for a, t, m in rows if t]
    return ArchivePlaylist(id=playlist_id, name=found[0][0], tracks=tracks)


async def _get(connect: DbConnect, playlist_id: str) -> ArchivePlaylist:
    playlist = await _run(connect, lambda conn: load_archive_playlist(conn, playlist_id))
    if playlist is None:
        raise HTTPException(404, f"Archive playlist {playlist_id} not found")
    return playlist


@router.get("/playlists", response_model=list[ArchivePlaylistSummary])
async def archive_playlists(db: Db) -> list[ArchivePlaylistSummary]:
    return await _run(db, list_archive)


@router.get(
    "/playlists/{playlist_id}", response_model=ArchivePlaylist, response_model_exclude_none=True
)
async def archive_playlist(playlist_id: str, db: Db) -> ArchivePlaylist:
    return await _get(db, playlist_id)


@router.post(
    "/playlists/{playlist_id}/copy", response_model=CopyResult, response_model_exclude_none=True
)
async def copy_to_library(
    playlist_id: str, client: Subsonic, db: Db, body: CopyRequest | None = None
) -> CopyResult:
    archived = await _get(db, playlist_id)
    name = (body.name.strip() if body and body.name else "") or archived.name
    refs = [TrackRef(artist=t.artist, title=t.title, mbid=t.mbid or "") for t in archived.tracks]
    song_ids, missed = await song_ids_for(client, refs, cache=DuckDBMatchCache(db))
    unmatched = [archived.tracks[i] for i in missed]
    playlist = await client.create_playlist(name, song_ids)
    log.info(
        "api.archive.copied",
        archive_id=playlist_id,
        playlist_id=playlist.id,
        matched=len(song_ids),
        unmatched=len(unmatched),
    )
    return CopyResult(playlist=playlist, unmatched=unmatched)
