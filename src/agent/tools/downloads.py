"""Legal downloads (Jamendo CC catalogue, Internet Archive) into the local library."""

from __future__ import annotations

import duckdb
from langchain_core.tools import StructuredTool

from agent.tools.discover import db
from library.downloads import download, find_free
from sources import musicbrainz
from sources.schemas import FreeTrack
from utils.exceptions import SourceError
from utils.logging import get_logger

log = get_logger(__name__)

_NONE_FOUND = (
    "No free, legal download found for {query} — Jamendo and the Internet Archive mostly "
    "carry independent / Creative Commons music and live recordings. Bandcamp sells "
    "DRM-free downloads of most other artists."
)


def _describe(t: FreeTrack) -> str:
    licence = f", licence: {t.license_url}" if t.license_url else ""
    return f"{t.artist} — {t.title} ({t.source}{licence})"


def _find_free_downloads(artist: str, title: str = "", n: int = 10) -> str:
    tracks = find_free(artist, title, limit=n)
    if not tracks:
        return _NONE_FOUND.format(query=f"{artist} — {title}" if title else artist)
    return "\n".join(f"{i}. {_describe(t)}" for i, t in enumerate(tracks, 1))


find_free_downloads_tool = StructuredTool.from_function(
    _find_free_downloads,
    name="find_free_downloads",
    description=(
        "Search legally downloadable copies of an artist's music (optionally one track "
        "title) on Jamendo (Creative Commons) and the Internet Archive (live recordings, "
        "netlabels, public domain). Use when the user asks what they can download or keep "
        "offline."
    ),
)


def _recording_mbid(artist: str, title: str) -> str:
    """Best-effort MusicBrainz recording MBID for tagging; '' when unsure or unreachable."""
    try:
        rec = musicbrainz.best_match(artist, title)
    except SourceError as exc:
        log.warning("agent.tools.mbid_lookup_failed", artist=artist, error=str(exc))
        return ""
    return rec.mbid if rec else ""


def _download_track(artist: str, title: str, mbid: str = "") -> str:
    tracks = find_free(artist, title, limit=1)
    if not tracks:
        return _NONE_FOUND.format(query=f"{artist} — {title}")
    track = tracks[0]
    mbid = mbid or _recording_mbid(track.artist, track.title)
    try:
        with db(write=True) as conn:  # records the file + licence in `library`
            path = download(conn, track, mbid=mbid, requested=(artist, title))
    except (duckdb.IOException, duckdb.ConnectionException) as exc:
        log.warning("agent.tools.download_db_locked", artist=artist, title=title, error=str(exc))
        return (
            f"Download of {artist} — {title} not started: the library database is in use by "
            "another process (the player API is its writer). Retry in a moment, or ask the "
            "player's assistant to download it."
        )
    except SourceError as exc:
        log.warning("agent.tools.download_failed", artist=artist, title=title, error=str(exc))
        return f"Download failed for {artist} — {title}: {exc}"
    return f"Downloaded {_describe(track)} to {path}"


download_track_tool = StructuredTool.from_function(
    _download_track,
    name="download_track",
    description=(
        "Download a track into the user's local library (served to their phone via "
        "Navidrome) — only from legal free sources (Jamendo, Internet Archive). Only call "
        "when the user explicitly asks to download. Never offers YouTube/Deezer downloads."
    ),
)
