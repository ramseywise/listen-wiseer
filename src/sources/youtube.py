"""
YouTube links for full-track playback — embed iframe only (ToS-clean, no downloading).
Search links need nothing; resolving a video ID needs YOUTUBE_API_KEY
(Data API v3: search = 100 quota units, 10k/day free → ~100 lookups/day).
"""

from functools import cache
from urllib.parse import urlencode

from sources.http import SourceClient
from utils.config import settings

_BASE_URL = "https://www.googleapis.com/youtube/v3/"


@cache
def default_client() -> SourceClient | None:
    if not settings.youtube_api_key:
        return None
    return SourceClient("youtube", _BASE_URL, params={"key": settings.youtube_api_key})


def search_url(artist: str, title: str) -> str:
    return "https://www.youtube.com/results?" + urlencode({"search_query": f"{artist} {title}"})


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def embed_url(video_id: str) -> str:
    return f"https://www.youtube.com/embed/{video_id}"


def find_video_id(artist: str, title: str, *, client: SourceClient | None = None) -> str | None:
    """First music-category video for artist + title; None without an API key."""
    c = client or default_client()
    if c is None:
        return None
    data = c.get_json(
        "search",
        part="snippet",
        type="video",
        videoCategoryId="10",  # Music
        maxResults=1,
        q=f"{artist} {title}",
    )
    items = data.get("items", [])
    return items[0]["id"]["videoId"] if items else None
