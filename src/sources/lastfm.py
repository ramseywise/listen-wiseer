"""
Last.fm similarity client — replaces Spotify related-artists / recommendations.
Track tags for genre matching stay in ``etl.lastfm``.

API docs: https://www.last.fm/api/show/track.getSimilar
"""

from functools import cache

from sources.http import SourceClient
from sources.schemas import SimilarItem
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

_BASE_URL = "https://ws.audioscrobbler.com/2.0/"
_MIN_INTERVAL = 0.25


@cache
def default_client() -> SourceClient | None:
    if not settings.last_fm_api_key:
        log.warning("lastfm.no_api_key")
        return None
    return SourceClient(
        "lastfm",
        _BASE_URL,
        min_interval=_MIN_INTERVAL,
        params={"api_key": settings.last_fm_api_key, "format": "json", "autocorrect": "1"},
    )


def _as_list(value: list | dict | None) -> list[dict]:
    # Last.fm returns a bare object instead of a one-element list
    if value is None:
        return []
    return [value] if isinstance(value, dict) else value


def _call(client: SourceClient | None, method: str, **params) -> dict:
    c = client or default_client()
    if c is None:
        return {}
    data = c.get_json("", method=method, **params)
    if "error" in data:
        log.debug("lastfm.api_error", method=method, code=data["error"], msg=data.get("message"))
        return {}
    return data


def similar_tracks(
    artist: str, title: str, *, limit: int = 20, client: SourceClient | None = None
) -> list[SimilarItem]:
    data = _call(client, "track.getsimilar", artist=artist, track=title, limit=limit)
    return [
        SimilarItem(
            source="lastfm",
            artist=t.get("artist", {}).get("name", ""),
            title=t.get("name", ""),
            mbid=t.get("mbid") or "",
            match=float(t.get("match", 0.0)),
        )
        for t in _as_list(data.get("similartracks", {}).get("track"))
    ]


def similar_artists(
    artist: str, *, limit: int = 20, client: SourceClient | None = None
) -> list[SimilarItem]:
    data = _call(client, "artist.getsimilar", artist=artist, limit=limit)
    return [
        SimilarItem(
            source="lastfm",
            artist=a.get("name", ""),
            mbid=a.get("mbid") or "",
            match=float(a.get("match", 0.0)),
        )
        for a in _as_list(data.get("similarartists", {}).get("artist"))
    ]
