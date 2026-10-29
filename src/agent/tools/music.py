"""Listening history (local `plays`) and artist/track lookups (MusicBrainz, Last.fm, Deezer).

Replaces the Spotify read tools; names are kept where the behaviour carries over.
History is empty until a Spotify privacy export is imported (etl.history).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

import duckdb
from langchain_core.tools import StructuredTool

from agent.tools.discover import db
from etl.resolve import MIN_MS_PLAYED
from sources import deezer, lastfm, musicbrainz
from sources.schemas import SimilarItem
from utils.exceptions import SourceError
from utils.logging import get_logger

log = get_logger(__name__)

_PERIOD_DAYS = {"4w": 28, "6m": 182, "1y": 365, "all": None}
_NO_HISTORY = (
    "No listening history yet. Import a Spotify privacy export into data/listening_history/ "
    "(make import-history)."
)


def _since(period: str) -> datetime:
    days = _PERIOD_DAYS.get(period, 182)
    return datetime.min if days is None else datetime.now() - timedelta(days=days)


_TOP_SQL = {
    "track": """
        SELECT any_value(artist_name), any_value(track_name), count(*) AS n FROM plays
        WHERE ms_played >= ? AND ts >= ? GROUP BY track_key ORDER BY n DESC LIMIT ?
    """,
    "artist": """
        SELECT artist_name, count(*) AS n FROM plays
        WHERE ms_played >= ? AND ts >= ? GROUP BY artist_name ORDER BY n DESC LIMIT ?
    """,
}


def _top(
    conn: duckdb.DuckDBPyConnection, by: Literal["track", "artist"], since: datetime, limit: int
) -> list[tuple]:
    return conn.execute(_TOP_SQL[by], [MIN_MS_PLAYED, since, limit]).fetchall()


def _get_recently_played(limit: int = 20) -> str:
    with db() as conn:
        rows = conn.execute(
            "SELECT ts, artist_name, track_name FROM plays WHERE ms_played >= ?"
            " ORDER BY ts DESC LIMIT ?",
            [MIN_MS_PLAYED, limit],
        ).fetchall()
    if not rows:
        return _NO_HISTORY
    return "\n".join(f"{i}. {a} — {t} ({ts:%Y-%m-%d})" for i, (ts, a, t) in enumerate(rows, 1))


get_recently_played_tool = StructuredTool.from_function(
    _get_recently_played,
    name="get_recently_played",
    description="The user's most recently played tracks from their imported listening history.",
)


def _get_top_tracks(period: str = "6m", limit: int = 20) -> str:
    with db() as conn:
        rows = _top(conn, "track", _since(period), limit)
    if not rows:
        return _NO_HISTORY
    return "\n".join(f"{i}. {a} — {t} ({n} plays)" for i, (a, t, n) in enumerate(rows, 1))


get_top_tracks_tool = StructuredTool.from_function(
    _get_top_tracks,
    name="get_top_tracks",
    description=(
        "The user's most-played tracks. period: '4w', '6m', '1y' or 'all'. "
        "Use for 'what have I been listening to'."
    ),
)


def _get_top_artists(period: str = "6m", limit: int = 20) -> str:
    with db() as conn:
        rows = _top(conn, "artist", _since(period), limit)
    if not rows:
        return _NO_HISTORY
    return "\n".join(f"{i}. {a} ({n} plays)" for i, (a, n) in enumerate(rows, 1))


get_top_artists_tool = StructuredTool.from_function(
    _get_top_artists,
    name="get_top_artists",
    description="The user's most-played artists. period: '4w', '6m', '1y' or 'all'.",
)


def _get_taste_analysis() -> str:
    with db() as conn:
        recent = [a for a, _ in _top(conn, "artist", _since("6m"), 15)]
        all_time = [a for a, _ in _top(conn, "artist", _since("all"), 15)]
    if not all_time:
        return _NO_HISTORY
    rising = [a for a in recent if a not in all_time]
    fading = [a for a in all_time if a not in recent]
    return "\n".join(
        [
            f"Top artists, last 6 months: {', '.join(recent) or '—'}",
            f"Top artists, all time: {', '.join(all_time)}",
            f"Rising (recent, not all-time top): {', '.join(rising) or '—'}",
            f"Fading (all-time top, not recent): {', '.join(fading) or '—'}",
        ]
    )


get_taste_analysis_tool = StructuredTool.from_function(
    _get_taste_analysis,
    name="get_taste_analysis",
    description="Compare the user's recent vs all-time top artists to show how their taste drifted.",
)


def _search_tracks(query: str, limit: int = 10) -> str:
    try:
        hits = deezer.search_tracks(query, limit=limit)
    except SourceError as exc:
        return f"Search failed: {exc}"
    if not hits:
        return f"No tracks found for '{query}'."
    return "\n".join(
        f"{i}. {t['artist']['name']} — {t['title']} ({t.get('album', {}).get('title', '')})"
        for i, t in enumerate(hits, 1)
    )


search_tracks_tool = StructuredTool.from_function(
    _search_tracks,
    name="search_tracks",
    description="Search for tracks by free text (artist, title, or both).",
)


def _get_artist_info(artist: str) -> str:
    try:
        mbid = musicbrainz.search_artist(artist)
        info = musicbrainz.get_artist(mbid) if mbid else None
    except SourceError as exc:
        return f"Failed to fetch artist info: {exc}"
    if info is None:
        return f"Artist '{artist}' not found in MusicBrainz."
    lines = [f"{info.name} ({info.type or 'artist'}, {info.country or 'unknown country'})"]
    if info.begin:
        lines.append(f"Active: {info.begin} – {info.end or 'present'}")
    if info.genres or info.tags:
        lines.append(f"Genres: {', '.join((info.genres or info.tags)[:8])}")
    if info.relations:
        rels = [f"{r.type}: {r.artist}" for r in info.relations[:10]]
        lines.append("Relations: " + "; ".join(rels))
    return "\n".join(lines)


get_artist_info_tool = StructuredTool.from_function(
    _get_artist_info,
    name="get_artist_info",
    description="Artist facts from MusicBrainz: type, country, active years, genres, band relations.",
)


def _get_related_artists(artist: str, limit: int = 15) -> str:
    items: list[SimilarItem] = []
    for fetch in (lastfm.similar_artists, deezer.related_artists):
        try:
            items += fetch(artist, limit=limit)
        except SourceError as exc:
            log.warning("agent.tools.related_artists.source_failed", error=str(exc))
    scores: dict[str, float] = {}
    names: dict[str, str] = {}
    for it in items:
        key = it.artist.casefold()
        names.setdefault(key, it.artist)
        scores[key] = scores.get(key, 0.0) + it.match
    if not scores:
        return f"No related artists found for {artist}."
    ranked = sorted(scores, key=lambda k: -scores[k])[:limit]
    return "\n".join(f"{i}. {names[k]}" for i, k in enumerate(ranked, 1))


get_related_artists_tool = StructuredTool.from_function(
    _get_related_artists,
    name="get_related_artists",
    description="Artists similar to the given artist (Last.fm + Deezer, merged).",
)


def _get_artist_top_tracks(artist: str, limit: int = 10) -> tuple[str, dict]:
    try:
        tracks = lastfm.artist_top_tracks(artist, limit=limit)
    except SourceError as exc:
        return f"Failed to fetch top tracks: {exc}", {}
    if not tracks:
        return f"No top tracks found for {artist}.", {}
    content = "\n".join(f"{i}. {t.artist} — {t.title}" for i, t in enumerate(tracks, 1))
    return content, {"tracks": [t.model_dump() for t in tracks]}


get_artist_top_tracks_tool = StructuredTool.from_function(
    _get_artist_top_tracks,
    name="get_artist_top_tracks",
    description="An artist's most popular tracks (Last.fm).",
    response_format="content_and_artifact",
)


def _get_artist_albums(artist: str) -> str:
    try:
        mbid = musicbrainz.search_artist(artist)
        albums = musicbrainz.artist_albums(mbid) if mbid else []
    except SourceError as exc:
        return f"Failed to fetch albums: {exc}"
    if not albums:
        return f"No albums found for {artist}."
    return "\n".join(f"- {a['title']} ({a['date'][:4] or '?'}, {a['type']})" for a in albums)


get_artist_albums_tool = StructuredTool.from_function(
    _get_artist_albums,
    name="get_artist_albums",
    description="An artist's albums and EPs in release order (MusicBrainz).",
)
