"""
Open-world discovery: rank tracks from free similarity sources around a seed.

Complements recommend/engine.py (closed-world, corpus only). Candidates:
  - track-level: Last.fm track.getSimilar, ListenBrainz LB Radio
  - artist-level: Last.fm artist.getSimilar, Deezer related — boost tracks by those artists
LB CF recs are recording-MBID only (no artist/title) and need history; S3b.

S3a heuristic, per track (deduped on track_key):
  W_AGREE · (track sources − 1) + W_MATCH · mean per-source match
  + W_ARTIST · artist-level support − W_PLAYED · log1p(own plays)
then cap tracks per artist and mix known vs new artists.
"""

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

import duckdb

from etl.history import track_key
from etl.resolve import MIN_MS_PLAYED
from sources import deezer, lastfm, listenbrainz
from sources.http import SourceClient
from sources.schemas import SimilarItem, TrackRef
from utils.exceptions import SourceError
from utils.logging import get_logger

log = get_logger(__name__)

W_AGREE = 1.0
W_MATCH = 1.0
W_ARTIST = 0.5
W_PLAYED = 0.3
MAX_PER_ARTIST = 2


class Candidate(TrackRef):
    score: float
    sources: list[str]
    known_artist: bool
    n_plays: int = 0


@dataclass
class History:
    play_counts: dict[str, int] = field(default_factory=dict)  # track_key → real plays
    known_artists: set[str] = field(default_factory=set)  # casefolded


def _artist_key(name: str) -> str:
    return name.strip().lower()


def load_history(conn: duckdb.DuckDBPyConnection) -> History:
    rows = conn.execute(
        """
        SELECT track_key, any_value(artist_name), count(*)
        FROM plays WHERE ms_played >= ?
        GROUP BY track_key
        """,
        [MIN_MS_PLAYED],
    ).fetchall()
    return History(
        play_counts={key: n for key, _, n in rows},
        known_artists={_artist_key(artist) for _, artist, _ in rows},
    )


def gather(
    artist: str,
    title: str | None = None,
    *,
    limit: int = 30,
    lastfm_client: SourceClient | None = None,
    lb_client: SourceClient | None = None,
    deezer_client: SourceClient | None = None,
) -> list[SimilarItem]:
    """All candidates for the seed. Each source fails soft."""
    calls: list[tuple[str, Callable[[], list[SimilarItem]]]] = [
        (
            "listenbrainz.lb_radio",
            lambda: listenbrainz.lb_radio(f"artist:({artist})", client=lb_client),
        ),
        (
            "lastfm.similar_artists",
            lambda: lastfm.similar_artists(artist, limit=limit, client=lastfm_client),
        ),
        (
            "deezer.related_artists",
            lambda: deezer.related_artists(artist, limit=limit, client=deezer_client),
        ),
    ]
    if title:
        calls.append(
            (
                "lastfm.similar_tracks",
                lambda: lastfm.similar_tracks(artist, title, limit=limit, client=lastfm_client),
            )
        )
    items: list[SimilarItem] = []
    for name, call in calls:
        try:
            got = call()
        except SourceError as exc:
            log.warning("discover.source_failed", source=name, error=str(exc))
            continue
        log.debug("discover.source", source=name, n=len(got))
        items += got
    return items


def _mix(ranked: list[Candidate], n: int, new_artist_ratio: float) -> list[Candidate]:
    per_artist: dict[str, int] = defaultdict(int)
    capped = []
    for c in ranked:
        a = _artist_key(c.artist)
        if per_artist[a] < MAX_PER_ARTIST:
            per_artist[a] += 1
            capped.append(c)
    new = [c for c in capped if not c.known_artist]
    known = [c for c in capped if c.known_artist]
    n_new = min(len(new), round(n * new_artist_ratio))
    n_known = min(len(known), n - n_new)
    n_new = min(len(new), n - n_known)  # backfill when known artists run short
    return sorted(new[:n_new] + known[:n_known], key=lambda c: -c.score)


def rank(
    items: list[SimilarItem],
    history: History | None = None,
    *,
    seed_artist: str = "",
    seed_title: str | None = None,
    n: int = 20,
    new_artist_ratio: float = 0.5,
) -> list[Candidate]:
    history = history or History()
    known_artists = history.known_artists | ({_artist_key(seed_artist)} if seed_artist else set())

    tracks: dict[str, list[SimilarItem]] = defaultdict(list)
    artist_support: dict[str, dict[str, float]] = defaultdict(dict)  # artist → source → match
    for it in items:
        if not it.artist:
            continue  # MBID-only (LB CF) — needs resolution first
        if it.title:
            tracks[track_key(it.artist, it.title)].append(it)
        else:
            support = artist_support[_artist_key(it.artist)]
            support[it.source] = max(support.get(it.source, 0.0), it.match)
    n_artist_sources = len({s for support in artist_support.values() for s in support}) or 1

    seed_key = track_key(seed_artist, seed_title) if seed_title else None
    ranked = []
    for key, group in tracks.items():
        if key == seed_key:
            continue
        best: dict[str, float] = {}
        for g in group:
            best[g.source] = max(best.get(g.source, 0.0), g.match)
        artist = _artist_key(group[0].artist)
        n_plays = history.play_counts.get(key, 0)
        score = (
            W_AGREE * (len(best) - 1)
            + W_MATCH * sum(best.values()) / len(best)
            + W_ARTIST * sum(artist_support.get(artist, {}).values()) / n_artist_sources
            - W_PLAYED * math.log1p(n_plays)
        )
        ranked.append(
            Candidate(
                artist=group[0].artist,
                title=group[0].title,
                mbid=next((g.mbid for g in group if g.mbid), ""),
                score=round(score, 4),
                sources=sorted(best),
                known_artist=artist in known_artists,
                n_plays=n_plays,
            )
        )
    ranked.sort(key=lambda c: (-c.score, c.artist.lower(), c.title.lower()))
    return _mix(ranked, n, new_artist_ratio)


def discover(
    artist: str,
    title: str | None = None,
    *,
    conn: duckdb.DuckDBPyConnection | None = None,
    n: int = 20,
    new_artist_ratio: float = 0.5,
    lastfm_client: SourceClient | None = None,
    lb_client: SourceClient | None = None,
    deezer_client: SourceClient | None = None,
) -> list[Candidate]:
    """Ranked discovery around a seed artist (and optionally track).

    With ``conn``, own plays down-weight already-heavy rotation and define "known" artists.
    """
    history = load_history(conn) if conn is not None else History()
    items = gather(
        artist,
        title,
        lastfm_client=lastfm_client,
        lb_client=lb_client,
        deezer_client=deezer_client,
    )
    out = rank(
        items,
        history,
        seed_artist=artist,
        seed_title=title,
        n=n,
        new_artist_ratio=new_artist_ratio,
    )
    log.info("discover.done", seed=artist, n_items=len(items), n_out=len(out))
    return out
