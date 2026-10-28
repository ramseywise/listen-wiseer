"""
ListenBrainz client — collaborative-filtering recs and LB Radio playlists.
Requires a user token (Settings → profile) even for reads.

API docs: https://listenbrainz.readthedocs.io/en/latest/users/api/
"""

from functools import cache

from sources.http import SourceClient
from sources.schemas import SimilarItem
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

_BASE_URL = "https://api.listenbrainz.org/1/"
_RECORDING_PREFIX = "https://musicbrainz.org/recording/"


@cache
def default_client() -> SourceClient | None:
    if not settings.listenbrainz_token:
        log.warning("listenbrainz.no_token")
        return None
    return SourceClient(
        "listenbrainz",
        _BASE_URL,
        headers={"Authorization": f"Token {settings.listenbrainz_token}"},
    )


def cf_recommendations(
    user: str | None = None, *, count: int = 25, client: SourceClient | None = None
) -> list[SimilarItem]:
    """Per-user collaborative-filtering recordings (MBID + score only; no names).

    Empty when LB has not generated recs for the user yet (needs listen history).
    """
    c = client or default_client()
    user = user or settings.listenbrainz_user
    if c is None or not user:
        return []
    data = c.get_json(f"cf/recommendation/user/{user}/recording", count=count)
    return [
        SimilarItem(source="listenbrainz", mbid=r["recording_mbid"], match=float(r["score"]))
        for r in data.get("payload", {}).get("mbids", [])
    ]


def _recording_mbid(identifier: str | list[str]) -> str:
    ids = [identifier] if isinstance(identifier, str) else identifier
    for i in ids:
        if i.startswith(_RECORDING_PREFIX):
            return i.removeprefix(_RECORDING_PREFIX)
    return ""


def lb_radio(
    prompt: str, *, mode: str = "easy", client: SourceClient | None = None
) -> list[SimilarItem]:
    """Generate an LB Radio playlist, e.g. ``artist:(Radiohead)`` or ``tag:(shoegaze)``.

    Prompt syntax: https://troi.readthedocs.io/en/stable/lb_radio.html
    ``mode``: easy | medium | hard (how far from the prompt to wander).
    """
    c = client or default_client()
    if c is None:
        return []
    data = c.get_json("explore/lb-radio", prompt=prompt, mode=mode)
    tracks = data.get("payload", {}).get("jspf", {}).get("playlist", {}).get("track", [])
    n = len(tracks)
    return [
        SimilarItem(
            source="listenbrainz",
            artist=t.get("creator", ""),
            title=t.get("title", ""),
            mbid=_recording_mbid(t.get("identifier", [])),
            match=1.0 - i / n,
        )
        for i, t in enumerate(tracks)
    ]
