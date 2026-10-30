"""
Subsonic API client for Navidrome — browse, search, cover art, audio streams, scans.
Async (one shared ``httpx.AsyncClient`` per process); token auth on every request
(``u``, ``t = md5(password + salt)``, ``s``), so the password never goes over the wire.
Errors come back as HTTP 200 with ``status: "failed"`` and an ``error`` object.

Not built on ``SourceClient``: that one is sync, maps 404 to ``{}`` and retries 503 —
a local server wants none of that, and streaming needs async.

API docs: https://www.subsonic.org/pages/api.jsp · https://opensubsonic.netlify.app/
"""

import hashlib
import secrets
from typing import Any, Literal, NoReturn

import httpx
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from utils.config import Settings
from utils.exceptions import SourceError
from utils.logging import get_logger

log = get_logger(__name__)

API_VERSION = "1.16.1"
CLIENT_NAME = "listen-wiseer"
_TIMEOUT = httpx.Timeout(10.0, read=30.0)

# Subsonic error codes: 10 missing param, 40 wrong credentials, 41 token auth unsupported,
# 50 not authorised, 70 data not found.
_NOT_FOUND = 70
_AUTH_CODES = frozenset({40, 41, 42, 43, 44})

AlbumListType = Literal["recent", "newest", "frequent", "random", "alphabeticalByName"]


class SubsonicError(SourceError):
    """Navidrome answered with a Subsonic error envelope."""

    def __init__(self, code: int, message: str):
        super().__init__(f"subsonic error {code}: {message}")
        self.code = code
        self.message = message


class SubsonicNotFound(SubsonicError):
    """Requested song / album / artist does not exist (code 70)."""


class SubsonicUnavailable(SourceError):
    """Navidrome can't serve us: unreachable, HTTP 5xx, or it rejected our credentials."""


class _Model(BaseModel):
    """Subsonic JSON is camelCase; so is our API — validate and dump by alias."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class Song(_Model):
    id: str
    title: str
    artist: str = ""
    artist_id: str = ""
    album: str = ""
    album_id: str = ""
    track: int | None = None
    year: int | None = None
    duration: int = 0
    cover_art: str | None = None
    mbid: str | None = Field(None, validation_alias=AliasChoices("musicBrainzId", "mbid"))
    suffix: str | None = None
    starred: bool = False  # Subsonic sends a timestamp when starred, nothing otherwise

    @field_validator("starred", mode="before")
    @classmethod
    def _starred(cls, v: Any) -> bool:
        return bool(v)

    @field_validator("title", mode="before")
    @classmethod
    def _strip_title(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @field_validator("mbid", "cover_art", "track", "year", mode="before")
    @classmethod
    def _blank_is_none(cls, v: Any) -> Any:
        return v or None


class AlbumSummary(_Model):
    id: str
    name: str
    artist: str = ""
    artist_id: str = ""
    year: int | None = None
    song_count: int = 0
    duration: int = 0
    cover_art: str | None = None

    @field_validator("year", "cover_art", mode="before")
    @classmethod
    def _blank_is_none(cls, v: Any) -> Any:
        return v or None


class Album(AlbumSummary):
    songs: list[Song] = Field(default_factory=list, validation_alias=AliasChoices("song", "songs"))


class ArtistSummary(_Model):
    id: str
    name: str
    album_count: int = 0
    cover_art: str | None = None

    @field_validator("cover_art", mode="before")
    @classmethod
    def _blank_is_none(cls, v: Any) -> Any:
        return v or None


class Artist(ArtistSummary):
    albums: list[AlbumSummary] = Field(
        default_factory=list, validation_alias=AliasChoices("album", "albums")
    )


class SearchResults(_Model):
    artists: list[ArtistSummary] = Field(
        default_factory=list, validation_alias=AliasChoices("artist", "artists")
    )
    albums: list[AlbumSummary] = Field(
        default_factory=list, validation_alias=AliasChoices("album", "albums")
    )
    songs: list[Song] = Field(default_factory=list, validation_alias=AliasChoices("song", "songs"))


class PlaylistSummary(_Model):
    id: str
    name: str
    song_count: int = 0
    duration: int = 0
    cover_art: str | None = None
    changed: str = ""  # ISO timestamp, as Navidrome sends it

    @field_validator("cover_art", mode="before")
    @classmethod
    def _blank_is_none(cls, v: Any) -> Any:
        return v or None


class Playlist(PlaylistSummary):
    songs: list[Song] = Field(default_factory=list, validation_alias=AliasChoices("entry", "songs"))


class PlayQueue(BaseModel):
    """Saved play queue; ``position`` is milliseconds into ``current``, as Subsonic keeps it."""

    songs: list[Song] = Field(default_factory=list)
    current: str | None = None
    position_ms: int = 0


class ScanStatus(_Model):
    scanning: bool = False
    count: int = 0  # songs in the library
    folder_count: int = 0


class AlbumPage(BaseModel):
    albums: list[AlbumSummary]
    total: int | None = None  # Navidrome's x-total-count header, when it sends one


def token_params(user: str, password: str, salt: str | None = None) -> dict[str, str]:
    """Auth + protocol params for one request; a fresh salt each call unless given."""
    salt = salt or secrets.token_hex(8)
    return {
        "u": user,
        "t": hashlib.md5((password + salt).encode()).hexdigest(),  # noqa: S324 — Subsonic spec
        "s": salt,
        "v": API_VERSION,
        "c": CLIENT_NAME,
        "f": "json",
    }


def unwrap(payload: dict) -> dict:
    """Body of a ``subsonic-response`` envelope; raises on ``status: failed``."""
    body = payload.get("subsonic-response")
    if not isinstance(body, dict):
        raise SubsonicError(0, "response is not a subsonic-response envelope")
    if body.get("status") != "ok":
        err = body.get("error") or {}
        code, message = int(err.get("code", 0)), str(err.get("message", "unknown error"))
        if code == _NOT_FOUND:
            raise SubsonicNotFound(code, message)
        if code in _AUTH_CODES:
            raise SubsonicUnavailable(f"navidrome rejected credentials ({code}: {message})")
        raise SubsonicError(code, message)
    return body


def _is_envelope(response: httpx.Response) -> bool:
    """Binary endpoints (stream, getCoverArt) answer errors as JSON instead of bytes."""
    ctype = response.headers.get("content-type", "")
    return ctype.startswith(("application/json", "text/xml", "application/xml"))


class SubsonicClient:
    """Typed Subsonic calls over one ``httpx.AsyncClient``. Close with ``aclose()``."""

    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: httpx.Timeout | float = _TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self._user = user
        self._password = password
        self._http = httpx.AsyncClient(
            base_url=f"{self.base_url}/rest/", timeout=timeout, transport=transport
        )

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> "SubsonicClient":
        return cls(
            settings.navidrome_url, settings.navidrome_user, settings.navidrome_password, **kwargs
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def _params(self, params: dict[str, Any]) -> dict[str, Any]:
        clean = {k: v for k, v in params.items() if v is not None}
        return {**token_params(self._user, self._password), **clean}

    async def _get(self, endpoint: str, **params: Any) -> httpx.Response:
        try:
            response = await self._http.get(endpoint, params=self._params(params))
        except httpx.HTTPError as exc:
            raise SubsonicUnavailable(f"navidrome: {endpoint} failed: {exc}") from exc
        if response.status_code >= 500:
            raise SubsonicUnavailable(f"navidrome: HTTP {response.status_code} on {endpoint}")
        return response

    @staticmethod
    def _body(response: httpx.Response, endpoint: str) -> dict:
        if response.status_code == 404:
            raise SubsonicError(404, f"endpoint {endpoint} not found")
        try:
            payload = response.json()
        except ValueError as exc:
            raise SubsonicError(0, f"{endpoint}: non-JSON response") from exc
        return unwrap(payload)

    async def call(self, endpoint: str, **params: Any) -> dict:
        """JSON endpoint → unwrapped ``subsonic-response`` body."""
        return self._body(await self._get(endpoint, **params), endpoint)

    # ── Server ───────────────────────────────────────────────────────────────

    async def ping(self) -> bool:
        await self.call("ping")
        return True

    async def scan_status(self) -> ScanStatus:
        return ScanStatus.model_validate((await self.call("getScanStatus")).get("scanStatus", {}))

    async def start_scan(self, *, full: bool = False) -> ScanStatus:
        body = await self.call("startScan", fullScan="true" if full else None)
        return ScanStatus.model_validate(body.get("scanStatus", {}))

    # ── Browse / search ──────────────────────────────────────────────────────

    async def artists(self) -> list[ArtistSummary]:
        index = (await self.call("getArtists")).get("artists", {}).get("index", [])
        return [ArtistSummary.model_validate(a) for i in index for a in i.get("artist", [])]

    async def artist(self, artist_id: str) -> Artist:
        return Artist.model_validate((await self.call("getArtist", id=artist_id))["artist"])

    async def album(self, album_id: str) -> Album:
        return Album.model_validate((await self.call("getAlbum", id=album_id))["album"])

    async def song(self, song_id: str) -> Song:
        return Song.model_validate((await self.call("getSong", id=song_id))["song"])

    async def album_list(
        self, list_type: AlbumListType, *, size: int = 20, offset: int = 0
    ) -> AlbumPage:
        response = await self._get("getAlbumList2", type=list_type, size=size, offset=offset)
        body = self._body(response, "getAlbumList2")
        total = response.headers.get("x-total-count")
        return AlbumPage(
            albums=[
                AlbumSummary.model_validate(a) for a in body.get("albumList2", {}).get("album", [])
            ],
            total=int(total) if total and total.isdigit() else None,
        )

    async def search(self, query: str, *, limit: int = 20) -> SearchResults:
        body = await self.call(
            "search3", query=query, artistCount=limit, albumCount=limit, songCount=limit
        )
        return SearchResults.model_validate(body.get("searchResult3", {}))

    # ── Playlists ────────────────────────────────────────────────────────────

    async def playlists(self) -> list[PlaylistSummary]:
        body = await self.call("getPlaylists")
        return [
            PlaylistSummary.model_validate(p) for p in body.get("playlists", {}).get("playlist", [])
        ]

    async def playlist(self, playlist_id: str) -> Playlist:
        return Playlist.model_validate((await self.call("getPlaylist", id=playlist_id))["playlist"])

    async def create_playlist(
        self, name: str | None = None, song_ids: list[str] | None = None, *,
        playlist_id: str | None = None,
    ) -> Playlist:  # fmt: skip
        """New playlist, or — with ``playlist_id`` — replace an existing one's songs (reorder)."""
        body = await self.call(
            "createPlaylist", name=name, playlistId=playlist_id, songId=song_ids or None
        )
        if "playlist" in body:
            return Playlist.model_validate(body["playlist"])
        # Pre-1.14 servers answer with an empty body; only the replace path knows the id.
        if playlist_id:
            return await self.playlist(playlist_id)
        raise SubsonicError(0, "createPlaylist returned no playlist")

    async def update_playlist(
        self, playlist_id: str, *, name: str | None = None,
        add: list[str] | None = None, remove_indexes: list[int] | None = None,
    ) -> None:  # fmt: skip
        await self.call(
            "updatePlaylist",
            playlistId=playlist_id,
            name=name,
            songIdToAdd=add or None,
            songIndexToRemove=remove_indexes or None,
        )

    async def delete_playlist(self, playlist_id: str) -> None:
        await self.call("deletePlaylist", id=playlist_id)

    # ── Favourites / play tracking ───────────────────────────────────────────

    async def starred_songs(self) -> list[Song]:
        body = await self.call("getStarred2")
        return [Song.model_validate(s) for s in body.get("starred2", {}).get("song", [])]

    async def star(self, song_id: str) -> None:
        await self.call("star", id=song_id)

    async def unstar(self, song_id: str) -> None:
        await self.call("unstar", id=song_id)

    async def scrobble(self, song_id: str, *, submission: bool, time_ms: int | None = None) -> None:
        await self.call(
            "scrobble", id=song_id, submission="true" if submission else "false", time=time_ms
        )

    async def play_queue(self) -> PlayQueue:
        """Saved queue; empty when none was ever saved (Navidrome omits ``playQueue``)."""
        raw = (await self.call("getPlayQueue")).get("playQueue") or {}
        return PlayQueue(
            songs=[Song.model_validate(s) for s in raw.get("entry", [])],
            current=str(raw["current"]) if raw.get("current") else None,
            position_ms=int(raw.get("position") or 0),
        )

    async def save_play_queue(
        self, song_ids: list[str], *, current: str | None = None, position_ms: int = 0
    ) -> None:
        await self.call(
            "savePlayQueue",
            id=song_ids or None,
            current=current if song_ids else None,
            position=position_ms if song_ids else None,
        )

    # ── Binary ───────────────────────────────────────────────────────────────

    async def open_stream(self, song_id: str, *, range_header: str | None = None) -> httpx.Response:
        """Start streaming the original file (no transcode, so byte ranges stay valid).

        The caller owns the returned response and must ``aclose()`` it.
        """
        request = self._http.build_request(
            "GET",
            "stream",
            params=self._params({"id": song_id, "format": "raw"}),
            # identity: raw bytes relayed as-is must match Content-Length / Content-Range
            headers={"Accept-Encoding": "identity"}
            | ({"Range": range_header} if range_header else {}),
        )
        try:
            response = await self._http.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise SubsonicUnavailable(f"navidrome: stream failed: {exc}") from exc
        if response.status_code >= 500 or _is_envelope(response) or response.status_code == 404:
            try:
                await response.aread()
            finally:
                await response.aclose()
            self._raise_for_binary(response, "stream")
        return response

    async def cover_art(self, cover_id: str, *, size: int | None = None) -> httpx.Response:
        """Cover image (body read). Navidrome serves a placeholder for items without art."""
        response = await self._get("getCoverArt", id=cover_id, size=size)
        if _is_envelope(response) or response.is_error:
            self._raise_for_binary(response, "getCoverArt")
        return response

    @staticmethod
    def _raise_for_binary(response: httpx.Response, endpoint: str) -> NoReturn:
        if response.status_code >= 500:
            raise SubsonicUnavailable(f"navidrome: HTTP {response.status_code} on {endpoint}")
        if response.status_code == 404:
            raise SubsonicNotFound(404, f"{endpoint}: not found")
        try:
            unwrap(response.json())
        except ValueError as exc:
            raise SubsonicError(0, f"{endpoint}: unexpected response") from exc
        raise SubsonicError(response.status_code, f"{endpoint}: HTTP {response.status_code}")
