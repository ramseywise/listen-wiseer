"""``/api/playable`` — how to play a track by identity: library song first (``library.match``),
else a Deezer 30s preview + YouTube link (``library.playback``, YouTube ids cached in DuckDB).
Also the batch enrichment ``/api/chat`` applies to the agent's tracks."""

import asyncio
from collections.abc import Callable, Sequence
from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from agent.tools.discover import resolve_track
from api.deps import Subsonic
from library.match import DEFAULT_CONCURRENCY, DuckDBMatchCache, MatchCache, MatchResult
from library.match import match_tracks as match_library
from sources.schemas import PlayableTrack, TrackRef
from sources.subsonic import Song, SubsonicClient
from utils.exceptions import SourceError
from utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["playable"])

Fallback = Callable[[str, str], PlayableTrack]  # (artist, title) → previews / links; blocking


class Playable(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    artist: str
    title: str
    song_id: str | None = None  # in the library
    preview_url: str | None = None
    youtube_url: str | None = None
    cover_url: str | None = None
    song: Song | None = None  # the library song, so the UI can queue it without a lookup


class ChatTrack(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    artist: str
    title: str
    mbid: str | None = None
    playable: Playable


def cover_url(cover_art: str | None, size: int = 300) -> str | None:
    return f"/api/cover/{cover_art}?size={size}" if cover_art else None


def _from_match(ref: TrackRef, hit: MatchResult) -> Playable:
    song = hit.song
    return Playable(
        artist=ref.artist,
        title=ref.title,
        song_id=hit.song_id,
        cover_url=cover_url(song.cover_art if song else None),
        song=song,
    )


def _from_fallback(ref: TrackRef, p: PlayableTrack) -> Playable:
    return Playable(
        artist=ref.artist,
        title=ref.title,
        preview_url=p.preview_url or None,
        youtube_url=p.youtube_url or None,
    )


async def _fallback(ref: TrackRef, fallback: Fallback) -> Playable:
    try:
        p = await asyncio.to_thread(fallback, ref.artist, ref.title)
    except (SourceError, duckdb.Error) as exc:
        log.warning("api.playable.fallback_failed", artist=ref.artist, error=str(exc))
        return Playable(artist=ref.artist, title=ref.title)
    return _from_fallback(ref, p)


async def resolve_many(
    client: SubsonicClient,
    refs: Sequence[TrackRef],
    *,
    cache: MatchCache | None,
    fallback: Fallback,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> list[Playable]:
    """Library match for every ref (one batch); previews / links for the misses, concurrently.
    Navidrome down → everything falls back rather than failing."""
    try:
        hits = await match_library(client, refs, cache=cache, concurrency=concurrency)
    except SourceError as exc:
        log.warning("api.playable.match_failed", n=len(refs), error=str(exc))
        hits = [None] * len(refs)
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(ref: TrackRef, hit: MatchResult | None) -> Playable:
        if hit is not None:
            return _from_match(ref, hit)
        async with sem:
            return await _fallback(ref, fallback)

    return list(await asyncio.gather(*(one(r, h) for r, h in zip(refs, hits, strict=True))))


# ── Dependencies (overridden in tests) ───────────────────────────────────────


def get_match_cache(request: Request) -> MatchCache:
    cache = getattr(request.app.state, "match_cache", None)
    if cache is None:
        cache = DuckDBMatchCache(request.app.state.db_connect)
        request.app.state.match_cache = cache
    return cache


def get_fallback() -> Fallback:
    return resolve_track


Cache = Annotated[MatchCache, Depends(get_match_cache)]
FallbackDep = Annotated[Fallback, Depends(get_fallback)]


@router.get("/playable", response_model=Playable, response_model_exclude_none=True)
async def playable(
    client: Subsonic,
    cache: Cache,
    fallback: FallbackDep,
    artist: Annotated[str, Query(min_length=1)],
    title: Annotated[str, Query(min_length=1)],
    mbid: str = "",
) -> Playable:
    ref = TrackRef(artist=artist, title=title, mbid=mbid)
    return (await resolve_many(client, [ref], cache=cache, fallback=fallback))[0]
