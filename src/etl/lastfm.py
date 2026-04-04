"""
Last.fm tag fetching for genre enrichment.

Used to derive first_genre for tracks that have no Spotify audio features
(Spotify deprecated the audio-features endpoint).

API docs: https://www.last.fm/api/show/track.getTopTags
No OAuth — requires only an API key (LASTFM_API_KEY in .env).
"""

from __future__ import annotations

import time

import httpx

from utils.logging import get_logger

log = get_logger(__name__)

_BASE_URL = "https://ws.audioscrobbler.com/2.0/"
_BATCH_SLEEP = 0.25  # 4 req/s — well within free tier (5/s)


def fetch_track_tags(
    artist: str,
    title: str,
    api_key: str,
    *,
    autocorrect: int = 1,
    min_count: int = 5,
) -> list[str]:
    """Fetch top tags for a track from Last.fm.

    Args:
        artist: Artist name.
        title: Track title.
        api_key: Last.fm API key.
        autocorrect: 1 = let Last.fm correct artist/track typos.
        min_count: Minimum tag count to include (filters noise).

    Returns:
        Tag names ordered by count descending, lowercased.
        Empty list if track not found or API error.
    """
    params = {
        "method": "track.getTopTags",
        "artist": artist,
        "track": title,
        "api_key": api_key,
        "autocorrect": str(autocorrect),
        "format": "json",
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        toptags = data.get("toptags", {})
        if "error" in data:
            log.debug(
                "lastfm.fetch.error",
                artist=artist,
                title=title,
                code=data.get("error"),
                message=data.get("message"),
            )
            return []

        tags = toptags.get("tag", [])
        if isinstance(tags, dict):
            # Single tag comes back as a dict, not a list
            tags = [tags]

        return [
            t["name"].lower()
            for t in tags
            if isinstance(t, dict) and int(t.get("count", 0)) >= min_count
        ]

    except httpx.HTTPError as exc:
        log.warning("lastfm.fetch.http_error", artist=artist, title=title, error=str(exc))
        return []


def match_genre(tags: list[str], genre_xy_set: set[str]) -> str | None:
    """Return the first tag that exists in the genre_xy set.

    Args:
        tags: Ordered tag names (lowercased) from fetch_track_tags.
        genre_xy_set: Set of all first_genre values from the genre_xy table.

    Returns:
        Matched genre string, or None if no tag matches.
    """
    for tag in tags:
        if tag in genre_xy_set:
            return tag
    return None


def fetch_genres_for_tracks(
    tracks: list[dict],
    api_key: str,
    genre_xy_set: set[str],
    *,
    sleep: float = _BATCH_SLEEP,
) -> dict[str, str | None]:
    """Batch-fetch Last.fm genres for a list of tracks.

    Args:
        tracks: List of dicts with keys ``track_id``, ``track_name``, ``artist_name``.
        api_key: Last.fm API key.
        genre_xy_set: Set of known genre_xy first_genre values for matching.
        sleep: Seconds to sleep between requests.

    Returns:
        Dict mapping track_id → matched genre (or None if no match).
    """
    results: dict[str, str | None] = {}
    for i, track in enumerate(tracks):
        tid = track["track_id"]
        tags = fetch_track_tags(track["artist_name"], track["track_name"], api_key)
        genre = match_genre(tags, genre_xy_set)
        results[tid] = genre
        log.debug(
            "lastfm.genre_match",
            track_id=tid,
            track_name=track["track_name"],
            artist=track["artist_name"],
            tags=tags[:5],
            matched=genre,
        )
        if i < len(tracks) - 1:
            time.sleep(sleep)

    matched = sum(1 for v in results.values() if v is not None)
    log.info("lastfm.fetch_genres.done", total=len(tracks), matched=matched)
    return results
