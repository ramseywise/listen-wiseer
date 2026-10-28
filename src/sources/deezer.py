"""
Deezer public API client — track lookup, 30s previews, related artists.
No auth. Errors come back as HTTP 200 with an ``error`` object in the body.

API docs: https://developers.deezer.com/api
"""

from functools import cache

from sources.http import SourceClient
from sources.schemas import SimilarItem
from utils.logging import get_logger

log = get_logger(__name__)

_BASE_URL = "https://api.deezer.com/"
_MIN_INTERVAL = 0.12  # documented quota: 50 req / 5s


@cache
def default_client() -> SourceClient:
    return SourceClient("deezer", _BASE_URL, min_interval=_MIN_INTERVAL)


def _ok(data: dict, op: str) -> bool:
    if "error" in data:
        log.debug("deezer.api_error", op=op, error=data["error"])
        return False
    return bool(data)


def _same_artist(expected: str, track: dict) -> bool:
    found = track.get("artist", {}).get("name", "").casefold()
    want = expected.casefold()
    return bool(found) and (want in found or found in want)


def find_track(artist: str, title: str, *, client: SourceClient | None = None) -> dict | None:
    """Best Deezer track for artist + title, or None.

    Tries the strict field query first, then a plain query (catches titles like
    "Weird Fishes / Arpeggi"); plain-query hits must match the artist name.
    """
    c = client or default_client()
    strict = c.get_json("search", q=f'artist:"{artist}" track:"{title}"', limit=1)
    if _ok(strict, "search") and strict.get("data"):
        return strict["data"][0]

    loose = c.get_json("search", q=f"{artist} {title}", limit=5)
    if not _ok(loose, "search"):
        return None
    return next((t for t in loose.get("data", []) if _same_artist(artist, t)), None)


def find_by_isrc(isrc: str, *, client: SourceClient | None = None) -> dict | None:
    c = client or default_client()
    data = c.get_json(f"track/isrc:{isrc}")
    return data if _ok(data, "isrc") else None


def related_artists(
    artist: str, *, limit: int = 20, client: SourceClient | None = None
) -> list[SimilarItem]:
    """Deezer's related artists. ``match`` is rank-derived (1.0 = first) — Deezer gives no score."""
    c = client or default_client()
    found = c.get_json("search/artist", q=artist, limit=1)
    if not _ok(found, "search_artist") or not found.get("data"):
        return []
    artist_id = found["data"][0]["id"]

    related = c.get_json(f"artist/{artist_id}/related", limit=limit)
    if not _ok(related, "related"):
        return []
    items = related.get("data", [])
    return [
        SimilarItem(source="deezer", artist=a["name"], match=1.0 - i / len(items))
        for i, a in enumerate(items)
    ]
