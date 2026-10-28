"""
Resolve a track to free playback options: Deezer 30s preview + YouTube full track.
Each source fails soft — one being down never blocks the other.
"""

from sources import deezer, youtube
from sources.http import SourceClient
from sources.schemas import PlayableTrack
from utils.exceptions import SourceError
from utils.logging import get_logger

log = get_logger(__name__)


def resolve_playable(
    artist: str,
    title: str,
    *,
    deezer_client: SourceClient | None = None,
    youtube_client: SourceClient | None = None,
) -> PlayableTrack:
    track = PlayableTrack(artist=artist, title=title, youtube_url=youtube.search_url(artist, title))

    try:
        dz = deezer.find_track(artist, title, client=deezer_client)
    except SourceError as exc:
        log.warning("playable.deezer_failed", artist=artist, title=title, error=str(exc))
        dz = None
    if dz:
        track.deezer_id = dz.get("id")
        track.deezer_url = dz.get("link", "")
        track.preview_url = dz.get("preview", "")
        track.isrc = dz.get("isrc", "")

    try:
        video_id = youtube.find_video_id(artist, title, client=youtube_client)
    except SourceError as exc:
        log.warning("playable.youtube_failed", artist=artist, title=title, error=str(exc))
        video_id = None
    if video_id:
        track.youtube_url = youtube.watch_url(video_id)
        track.youtube_embed_url = youtube.embed_url(video_id)

    return track
