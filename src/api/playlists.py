"""Playlist + favourites routes — Navidrome is the source of truth (D2)."""

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from api.deps import Subsonic
from sources.subsonic import Playlist, PlaylistSummary, Song
from utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["playlists"])


class _Body(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class NewPlaylist(_Body):
    name: str = Field(min_length=1)
    song_ids: list[str] = Field(default_factory=list)


class PlaylistPatch(_Body):
    name: str | None = Field(None, min_length=1)
    song_ids: list[str] | None = None  # full new order — rewrites the playlist
    add: list[str] = Field(default_factory=list)
    remove_indexes: list[int] = Field(default_factory=list)


@router.get("/playlists", response_model=list[PlaylistSummary], response_model_exclude_none=True)
async def list_playlists(client: Subsonic) -> list[PlaylistSummary]:
    return await client.playlists()


@router.post(
    "/playlists", response_model=Playlist, response_model_exclude_none=True, status_code=201
)
async def create_playlist(body: NewPlaylist, client: Subsonic) -> Playlist:
    playlist = await client.create_playlist(body.name.strip(), body.song_ids)
    log.info("api.playlist.created", id=playlist.id, n_songs=len(body.song_ids))
    return playlist


@router.get("/playlists/{playlist_id}", response_model=Playlist, response_model_exclude_none=True)
async def get_playlist(playlist_id: str, client: Subsonic) -> Playlist:
    return await client.playlist(playlist_id)


@router.patch("/playlists/{playlist_id}", response_model=Playlist, response_model_exclude_none=True)
async def patch_playlist(playlist_id: str, body: PlaylistPatch, client: Subsonic) -> Playlist:
    """``songIds`` = full rewrite (Subsonic has no move); ``add`` / ``removeIndexes`` are
    incremental. A rewrite can't be combined with the incremental edits."""
    if body.song_ids is not None and (body.add or body.remove_indexes):
        raise HTTPException(422, "songIds is a full rewrite; don't combine it with add/remove")
    if body.song_ids is not None:
        if body.song_ids:
            await client.create_playlist(playlist_id=playlist_id, song_ids=body.song_ids)
        else:  # createPlaylist without songId keeps the old songs — clear by index instead
            current = await client.playlist(playlist_id)
            if current.songs:
                await client.update_playlist(
                    playlist_id, remove_indexes=list(range(len(current.songs)))
                )
    if body.name is not None or body.add or body.remove_indexes:
        await client.update_playlist(
            playlist_id,
            name=body.name.strip() if body.name else None,
            add=body.add,
            remove_indexes=body.remove_indexes,
        )
    return await client.playlist(playlist_id)


@router.delete("/playlists/{playlist_id}", status_code=204)
async def delete_playlist(playlist_id: str, client: Subsonic) -> Response:
    await client.delete_playlist(playlist_id)
    log.info("api.playlist.deleted", id=playlist_id)
    return Response(status_code=204)


@router.get("/starred", response_model=list[Song], response_model_exclude_none=True)
async def starred(client: Subsonic) -> list[Song]:
    return await client.starred_songs()


@router.put("/starred/{song_id}", status_code=204)
async def star(song_id: str, client: Subsonic) -> Response:
    await client.star(song_id)
    return Response(status_code=204)


@router.delete("/starred/{song_id}", status_code=204)
async def unstar(song_id: str, client: Subsonic) -> Response:
    await client.unstar(song_id)
    return Response(status_code=204)
