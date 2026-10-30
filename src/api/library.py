"""Library routes — a thin Subsonic proxy: browse, search, cover art, audio with Range."""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from starlette.background import BackgroundTask

from api.deps import Subsonic
from sources.subsonic import (
    Album,
    AlbumListType,
    AlbumSummary,
    Artist,
    ArtistSummary,
    SearchResults,
    Song,
)
from utils.exceptions import SourceError
from utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["library"])

# Upstream headers worth relaying; everything else (Navidrome's cookies, CSP) stays behind.
_STREAM_HEADERS = (
    "content-type",
    "content-length",
    "content-range",
    "accept-ranges",
    "last-modified",
    "etag",
    "x-content-duration",
)
_COVER_HEADERS = ("cache-control", "etag", "last-modified")
_COVER_CACHE = "public, max-age=86400"  # cover ids embed an update hash, so a day is safe


class Health(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    navidrome: bool
    song_count: int = 0


@router.get("/health", response_model=Health)
async def health(client: Subsonic) -> Health:
    """Always 200 — ``navidrome: false`` when it's down, so the UI can show why."""
    try:
        status = await client.scan_status()
    except SourceError as exc:
        log.info("api.health.navidrome_down", error=str(exc))
        return Health(navidrome=False)
    return Health(navidrome=True, song_count=status.count)


@router.get("/artists", response_model=list[ArtistSummary], response_model_exclude_none=True)
async def artists(client: Subsonic) -> list[ArtistSummary]:
    return await client.artists()


@router.get("/artists/{artist_id}", response_model=Artist, response_model_exclude_none=True)
async def artist(artist_id: str, client: Subsonic) -> Artist:
    return await client.artist(artist_id)


@router.get(
    "/artists/{artist_id}/songs", response_model=list[Song], response_model_exclude_none=True
)
async def artist_songs(artist_id: str, client: Subsonic) -> list[Song]:
    """Every song across the artist's albums, albums in ``getArtist`` order."""
    found = await client.artist(artist_id)
    albums = await asyncio.gather(*(client.album(a.id) for a in found.albums))
    return [song for album in albums for song in album.songs]


@router.get("/albums", response_model=list[AlbumSummary], response_model_exclude_none=True)
async def albums(
    client: Subsonic,
    response: Response,
    type: AlbumListType = "newest",  # contract query param name (shadows builtin)
    size: Annotated[int, Query(ge=1, le=500)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AlbumSummary]:
    page = await client.album_list(type, size=size, offset=offset)
    if page.total is not None:
        response.headers["X-Total-Count"] = str(page.total)
    return page.albums


@router.get("/albums/{album_id}", response_model=Album, response_model_exclude_none=True)
async def album(album_id: str, client: Subsonic) -> Album:
    return await client.album(album_id)


@router.get("/search", response_model=SearchResults, response_model_exclude_none=True)
async def search(
    client: Subsonic, q: str = "", limit: Annotated[int, Query(ge=1, le=200)] = 20
) -> SearchResults:
    # Subsonic treats an empty query as "everything" — not what a search box means.
    if not q.strip():
        return SearchResults()
    return await client.search(q.strip(), limit=limit)


@router.get("/cover/{cover_id}")
async def cover(
    cover_id: str, client: Subsonic, size: Annotated[int, Query(ge=16, le=2048)] = 300
) -> Response:
    upstream = await client.cover_art(cover_id, size=size)
    headers = {h: v for h in _COVER_HEADERS if (v := upstream.headers.get(h))}
    headers.setdefault("cache-control", _COVER_CACHE)
    return Response(
        upstream.content,
        media_type=upstream.headers.get("content-type", "image/jpeg"),
        headers=headers,
    )


async def _relay(upstream: httpx.Response) -> AsyncIterator[bytes]:
    """Upstream body as-is; closes the upstream when the client goes away mid-stream."""
    try:
        async for chunk in upstream.aiter_raw():
            yield chunk
    finally:
        await upstream.aclose()


@router.get("/stream/{song_id}")
async def stream(song_id: str, request: Request, client: Subsonic) -> StreamingResponse:
    """Original file bytes; ``Range`` goes upstream, so 206 / Content-Range come back intact
    and seeking works."""
    upstream = await client.open_stream(song_id, range_header=request.headers.get("range"))
    headers = {h: v for h in _STREAM_HEADERS if (v := upstream.headers.get(h))}
    headers.setdefault("accept-ranges", "bytes")
    return StreamingResponse(
        _relay(upstream),
        status_code=upstream.status_code,
        headers=headers,
        background=BackgroundTask(upstream.aclose),  # idempotent backstop to _relay's finally
    )
