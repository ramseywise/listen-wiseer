"""
Jamendo client — ~600k Creative Commons tracks with free MP3 downloads.
Needs JAMENDO_CLIENT_ID (devportal.jamendo.com). Errors come back as HTTP 200
with ``headers.status != "success"``.

API docs: https://developer.jamendo.com/v3.0/tracks
"""

from functools import cache

from sources.http import SourceClient
from sources.schemas import FreeTrack
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

_BASE_URL = "https://api.jamendo.com/v3.0/"


@cache
def default_client() -> SourceClient | None:
    if not settings.jamendo_client_id:
        return None
    return SourceClient(
        "jamendo", _BASE_URL, params={"client_id": settings.jamendo_client_id, "format": "json"}
    )


def find_tracks(
    artist: str, title: str = "", *, limit: int = 10, client: SourceClient | None = None
) -> list[FreeTrack]:
    """Downloadable tracks by ``artist`` (name search on ``title``); [] without a client_id."""
    c = client or default_client()
    if c is None:
        return []
    params: dict = {"artist_name": artist, "limit": limit, "audiodlformat": "mp32"}
    if title:
        params["namesearch"] = title
    data = c.get_json("tracks/", **params)
    if data.get("headers", {}).get("status") != "success":
        log.debug("jamendo.api_error", headers=data.get("headers"))
        return []
    return [
        FreeTrack(
            source="jamendo",
            source_id=str(t["id"]),
            artist=t["artist_name"],
            title=t["name"],
            download_url=t["audiodownload"],
            page_url=t.get("shareurl", ""),
            license_url=t.get("license_ccurl", ""),
        )
        for t in data.get("results", [])
        if t.get("audiodownload_allowed") and t.get("audiodownload")
    ]
