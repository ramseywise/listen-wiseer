"""Play tracking + queue persistence.

Scrobbles go to Navidrome (now-playing, play counts, its ListenBrainz/Last.fm forwarding) and
completed / skipped plays are also written to DuckDB ``plays`` — Subsonic keeps no history,
and ``plays`` is the reranker's label source (S3b). The queue lives in Navidrome
(``savePlayQueue``) so other Subsonic clients can resume it (D4).
"""

import asyncio
from datetime import UTC, datetime

import duckdb
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from api.deps import Db, DbConnect, Subsonic
from etl.db import init_schema
from etl.history import track_key
from sources.subsonic import Song
from utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/player", tags=["player"])


class _Body(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Scrobble(_Body):
    song_id: str = Field(min_length=1)
    submission: bool
    played_seconds: float | None = Field(None, ge=0)
    skipped: bool = False


class QueueState(_Body):
    song_ids: list[str] = Field(default_factory=list)
    current: str | None = None
    position: float = Field(0, ge=0)  # seconds into ``current``


class SavedQueue(QueueState):
    """GET also returns the songs (Navidrome sends them anyway) so the UI restores the queue
    without a lookup per id."""

    songs: list[Song] = Field(default_factory=list)


_INSERT_PLAY = """
INSERT OR IGNORE INTO plays
    (ts, track_key, track_name, artist_name, album_name, ms_played, skipped,
     navidrome_id, source)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'navidrome')
"""


def record_play(
    connect: DbConnect,
    song: Song,
    *,
    played_seconds: float | None,
    skipped: bool,
    ensure_schema: bool,
    ts: datetime | None = None,
) -> None:
    """One ``plays`` row; ``ts`` is naive UTC like the Spotify export's."""
    conn = connect()
    try:
        if ensure_schema:
            init_schema(conn)  # adds plays.navidrome_id / source on an older DB file
        conn.execute(
            _INSERT_PLAY,
            [
                ts or datetime.now(UTC).replace(tzinfo=None),
                track_key(song.artist, song.title),
                song.title,
                song.artist,
                song.album or None,
                round(played_seconds * 1000) if played_seconds is not None else None,
                skipped,
                song.id,
            ],
        )
    finally:
        conn.close()


@router.post("/scrobble", status_code=204)
async def scrobble(body: Scrobble, request: Request, client: Subsonic, db: Db) -> Response:
    """``submission=false`` = now playing. A completed play (``submission=true``) is forwarded
    and recorded; a skip is recorded only — it must not count as a play upstream."""
    if not body.submission:
        await client.scrobble(body.song_id, submission=False)
        return Response(status_code=204)

    if not body.skipped:
        await client.scrobble(body.song_id, submission=True)
    song = await client.song(body.song_id)
    state = request.app.state
    try:
        await asyncio.to_thread(
            record_play,
            db,
            song,
            played_seconds=body.played_seconds,
            skipped=body.skipped,
            ensure_schema=not getattr(state, "plays_schema_ready", False),
        )
        state.plays_schema_ready = True
    except duckdb.Error as exc:  # another process holds the write lock — keep playing
        log.warning("api.scrobble.db_write_failed", song_id=body.song_id, error=str(exc))
    log.info("api.scrobble.recorded", song_id=body.song_id, skipped=body.skipped)
    return Response(status_code=204)


@router.get("/queue", response_model=SavedQueue, response_model_exclude_none=True)
async def get_queue(client: Subsonic) -> SavedQueue:
    saved = await client.play_queue()
    return SavedQueue(
        songs=saved.songs,
        song_ids=[s.id for s in saved.songs],
        current=saved.current,
        position=saved.position_ms / 1000,
    )


@router.put("/queue", status_code=204)
async def put_queue(body: QueueState, client: Subsonic) -> Response:
    current = body.current if body.current in body.song_ids else None
    await client.save_play_queue(
        body.song_ids, current=current, position_ms=round(body.position * 1000)
    )
    return Response(status_code=204)
