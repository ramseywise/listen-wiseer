"""
Save a track list as a Navidrome playlist (D2 — Navidrome is the playlist source of truth).
Used by the agent's ``save_playlist`` tool and the MCP server's, both of which run outside
the API's client lifecycle, so they get a short-lived ``SubsonicClient`` from settings.

Tracks are matched to library songs via ``library.match``; the ones that miss are reported
back ("not in library") so the agent can offer previews or legal downloads instead.
"""

import asyncio
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from library.match import MatchCache, match_tracks
from sources.schemas import TrackRef
from sources.subsonic import PlaylistSummary, SubsonicClient
from utils.config import Settings, settings
from utils.exceptions import SourceError
from utils.logging import get_logger

log = get_logger(__name__)

_SYNC_TIMEOUT_S = 20.0


class NavidromeNotConfigured(SourceError):
    """NAVIDROME_USER / NAVIDROME_PASSWORD are not set."""


def navidrome_configured(cfg: Settings = settings) -> bool:
    return bool(cfg.navidrome_url and cfg.navidrome_user and cfg.navidrome_password)


def _client_from_settings() -> SubsonicClient:
    if not navidrome_configured():
        raise NavidromeNotConfigured("navidrome is not configured (NAVIDROME_USER / _PASSWORD)")
    return SubsonicClient.from_settings(settings)


@dataclass
class SavedPlaylist:
    name: str
    n_tracks: int
    playlist_id: str | None = None  # None = nothing matched, so no playlist was created
    matched: int = 0
    unmatched: list[TrackRef] = field(default_factory=list)


async def save_to_navidrome(
    name: str,
    tracks: Sequence[TrackRef],
    *,
    client: SubsonicClient | None = None,
    cache: MatchCache | None = None,
) -> SavedPlaylist:
    """Match ``tracks`` and create playlist ``name`` from the hits (input order, no repeats).

    Raises ``NavidromeNotConfigured`` / ``SubsonicUnavailable`` (both ``SourceError``).
    """
    own = client is None
    client = client or _client_from_settings()
    try:
        results = await match_tracks(client, tracks, cache=cache)
        song_ids = list(dict.fromkeys(r.song_id for r in results if r is not None))
        unmatched = [t for t, r in zip(tracks, results, strict=True) if r is None]
        saved = SavedPlaylist(name=name, n_tracks=len(tracks), unmatched=unmatched)
        saved.matched = len(tracks) - len(unmatched)
        if song_ids:
            playlist = await client.create_playlist(name, song_ids)
            saved.playlist_id = playlist.id
    finally:
        if own:
            await client.aclose()
    log.info(
        "navidrome_playlist.saved",
        name=name,
        playlist_id=saved.playlist_id,
        matched=saved.matched,
        unmatched=len(saved.unmatched),
    )
    return saved


def describe(saved: SavedPlaylist) -> str:
    """Tool-result text: what was saved, and which tracks the library doesn't have."""
    if saved.playlist_id:
        lines = [
            f"Saved playlist '{saved.name}' to the music library (Navidrome id {saved.playlist_id}):"
            f" {saved.matched} of {saved.n_tracks} tracks matched."
        ]
    else:
        lines = [
            f"Playlist '{saved.name}' was not created: none of its {saved.n_tracks} tracks are "
            "in the music library yet."
        ]
    if saved.unmatched:
        lines.append(
            f"Not in the library ({len(saved.unmatched)}) — offer 30s previews / YouTube "
            "(play_track) or legal downloads (find_free_downloads):"
        )
        lines += [f"- {t.artist} — {t.title}" for t in saved.unmatched]
    return "\n".join(lines)


async def list_navidrome_playlists() -> list[PlaylistSummary]:
    client = _client_from_settings()
    try:
        return await client.playlists()
    finally:
        await client.aclose()


def list_navidrome_playlists_sync() -> list[PlaylistSummary] | None:
    """For sync tools: runs on a private event loop in a worker thread, so it is safe whether
    or not the caller's thread has a loop running. None = not configured or unreachable."""
    if not navidrome_configured():
        return None
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, list_navidrome_playlists())
        try:
            return future.result(timeout=_SYNC_TIMEOUT_S)
        except (SourceError, TimeoutError) as exc:
            log.warning("navidrome_playlist.list_failed", error=str(exc))
            return None
