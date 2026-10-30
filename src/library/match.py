"""
Match a track identity (artist, title, optional MBID) to a song in the Navidrome library.

Order: cache (DuckDB ``track_xref.navidrome_id``, re-checked with ``getSong`` so deleted
files fall through) → ``search3`` on the MBID (Navidrome indexes MusicBrainz ids; an exact
``musicBrainzId`` hit is confidence 1.0) → ``search3`` on artist + title, then title alone
→ candidates scored on normalised artist / title against ``MATCH_THRESHOLD``.

Only hits are cached: a miss today may be a hit after the next download + library scan.
Navidrome being down raises ``SubsonicUnavailable`` — callers choose the fallback.
"""

import asyncio
import re
import threading
import unicodedata
from collections.abc import Callable, Sequence
from datetime import datetime
from difflib import SequenceMatcher
from typing import Literal, Protocol

import duckdb
from pydantic import BaseModel

from etl.db import get_connection, init_schema
from etl.history import track_key
from sources.schemas import TrackRef
from sources.subsonic import Song, SubsonicClient, SubsonicNotFound
from utils.logging import get_logger

log = get_logger(__name__)

MATCH_THRESHOLD = 0.85
_MIN_TITLE = 0.8  # a near-perfect artist can't rescue a different song
_MIN_ARTIST = 0.6
_SEARCH_LIMIT = 20
DEFAULT_CONCURRENCY = 8

_VERSION = (
    r"(?:remaster(?:ed)?|live|mono|stereo|explicit|clean|bonus\s+track|"
    r"deluxe(?:\s+edition)?|album\s+version|single\s+version|radio\s+edit|re-?recorded)"
)
_FEAT_BRACKET = re.compile(
    r"\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s[^\)\]]*[\)\]]", re.IGNORECASE
)
_FEAT_TAIL = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s.*$", re.IGNORECASE)
_VERSION_BRACKET = re.compile(rf"\s*[\(\[][^\)\]]*\b{_VERSION}\b[^\)\]]*[\)\]]", re.IGNORECASE)
_VERSION_DASH = re.compile(rf"\s+[-–—]\s+[^-–—]*\b{_VERSION}\b.*$", re.IGNORECASE)
_APOSTROPHES = re.compile(r"['’`´]")
_NON_WORD = re.compile(r"[\W_]+")
_ARTIST_SPLIT = re.compile(r"\s*(?:,|;|/|&|\s+x\s+|\s+and\s+|\s+vs\.?\s+)\s*", re.IGNORECASE)


class MatchResult(BaseModel):
    song_id: str
    confidence: float
    method: Literal["cache", "mbid", "search"]
    song: Song | None = None  # always set when found by search; set on cache hits too


# ── Normalisation ────────────────────────────────────────────────────────────


def _fold(s: str) -> str:
    """Casefold, drop accents and punctuation, ``&`` → ``and``, collapse whitespace."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    s = _APOSTROPHES.sub("", s.replace("&", " and "))
    return " ".join(_NON_WORD.sub(" ", s).split())


def _strip_credits(s: str) -> str:
    """Remove featured-artist credits and version suffixes (remaster / live / mono …)."""
    s = _FEAT_BRACKET.sub("", s)
    s = _VERSION_BRACKET.sub("", s)
    s = _VERSION_DASH.sub("", s)
    return _FEAT_TAIL.sub("", s).strip()


def normalize_title(title: str) -> str:
    return _fold(_strip_credits(title))


def normalize_artist(artist: str) -> str:
    folded = _fold(_strip_credits(artist))
    return folded.removeprefix("the ") if folded != "the" else folded


def _first_credit(artist: str) -> str:
    return _ARTIST_SPLIT.split(_strip_credits(artist), maxsplit=1)[0].strip()


def primary_artist(artist: str) -> str:
    """First credited artist: ``"A & B"`` / ``"A, B"`` / ``"A feat. B"`` → ``A`` (normalised)."""
    return normalize_artist(_first_credit(artist))


# ── Scoring ──────────────────────────────────────────────────────────────────


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


def _artist_similarity(a: str, b: str) -> float:
    full = _similarity(normalize_artist(a), normalize_artist(b))
    primary = _similarity(primary_artist(a), primary_artist(b))
    return max(full, 0.95 * primary)


def score(artist: str, title: str, song: Song, mbid: str = "") -> float:
    """0–1 confidence that ``song`` is (artist, title). An equal MBID is 1.0."""
    if mbid and song.mbid and song.mbid == mbid:
        return 1.0
    t = _similarity(normalize_title(title), normalize_title(song.title))
    a = _artist_similarity(artist, song.artist)
    conf = 0.6 * t + 0.4 * a
    if t < _MIN_TITLE or a < _MIN_ARTIST:
        return min(conf, MATCH_THRESHOLD - 0.01)
    return round(conf, 4)


def best_candidate(
    artist: str, title: str, songs: Sequence[Song], mbid: str = ""
) -> tuple[Song, float] | None:
    """Highest-scoring song (ties: first, i.e. Navidrome's relevance order)."""
    best: tuple[Song, float] | None = None
    for song in songs:
        s = score(artist, title, song, mbid)
        if best is None or s > best[1]:
            best = (song, s)
    return best


# ── Cache ────────────────────────────────────────────────────────────────────


class MatchCache(Protocol):
    """Sync (call via ``asyncio.to_thread``); fails soft — a broken cache never blocks matching."""

    def get_many(self, keys: Sequence[str]) -> dict[str, tuple[str, float]]: ...

    def put_many(self, rows: Sequence[tuple[str, str, str, str, float]]) -> None:
        """Rows of ``(track_key, artist, title, song_id, confidence)``."""
        ...

    def forget(self, keys: Sequence[str]) -> None: ...


class DuckDBMatchCache:
    """``track_xref.navidrome_*`` via short-lived connections (the MCP server / ETL may
    hold the file between calls). ``connect`` is injectable for tests.

    ``read_only`` (MCP server — the API owns the writer): lookups only, no migration,
    ``put_many`` / ``forget`` are no-ops."""

    def __init__(
        self,
        connect: Callable[[], duckdb.DuckDBPyConnection] = get_connection,
        *,
        read_only: bool = False,
    ):
        self._connect = connect
        self._lock = threading.Lock()
        self._schema_ready = read_only
        self.read_only = read_only

    def _open(self) -> duckdb.DuckDBPyConnection:
        conn = self._connect()
        if not self._schema_ready:
            init_schema(conn)  # adds the navidrome_* columns to existing DBs
            self._schema_ready = True
        return conn

    def get_many(self, keys: Sequence[str]) -> dict[str, tuple[str, float]]:
        if not keys:
            return {}
        try:
            with self._lock:
                conn = self._open()
                try:
                    rows = conn.execute(
                        "SELECT track_key, navidrome_id, navidrome_confidence FROM track_xref"
                        " WHERE navidrome_id IS NOT NULL AND list_contains(?, track_key)",
                        [list(keys)],
                    ).fetchall()
                finally:
                    conn.close()
        except duckdb.Error as exc:
            log.warning("match.cache.read_failed", error=str(exc))
            return {}
        return {k: (sid, float(conf or 0.0)) for k, sid, conf in rows}

    def put_many(self, rows: Sequence[tuple[str, str, str, str, float]]) -> None:
        if not rows or self.read_only:
            return
        now = datetime.now()
        try:
            with self._lock:
                conn = self._open()
                try:
                    conn.executemany(
                        """
                        INSERT INTO track_xref (track_key, artist_name, track_name,
                            navidrome_id, navidrome_confidence, navidrome_matched_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT (track_key) DO UPDATE SET
                            navidrome_id = excluded.navidrome_id,
                            navidrome_confidence = excluded.navidrome_confidence,
                            navidrome_matched_at = excluded.navidrome_matched_at
                        """,
                        [[*row, now] for row in rows],
                    )
                finally:
                    conn.close()
        except duckdb.Error as exc:
            log.warning("match.cache.write_failed", error=str(exc), n=len(rows))

    def forget(self, keys: Sequence[str]) -> None:
        if not keys or self.read_only:
            return
        try:
            with self._lock:
                conn = self._open()
                try:
                    conn.execute(
                        "UPDATE track_xref SET navidrome_id = NULL, navidrome_confidence = NULL,"
                        " navidrome_matched_at = NULL WHERE list_contains(?, track_key)",
                        [list(keys)],
                    )
                finally:
                    conn.close()
        except duckdb.Error as exc:
            log.warning("match.cache.forget_failed", error=str(exc))


_default_cache: DuckDBMatchCache | None = None


def default_cache() -> DuckDBMatchCache:
    """Process-wide cache over the project DuckDB file."""
    global _default_cache  # noqa: PLW0603
    if _default_cache is None:
        _default_cache = DuckDBMatchCache()
    return _default_cache


# ── Matching ─────────────────────────────────────────────────────────────────


def _search_query(*parts: str) -> str:
    """Credits / versions stripped, punctuation → spaces, accents kept for Navidrome."""
    words = " ".join(_NON_WORD.sub(" ", _strip_credits(p)) for p in parts)
    return " ".join(words.split())


async def _search_songs(client: SubsonicClient, query: str) -> list[Song]:
    if not query:
        return []
    return (await client.search(query, limit=_SEARCH_LIMIT)).songs


async def _search_match(
    client: SubsonicClient, artist: str, title: str, mbid: str, threshold: float
) -> MatchResult | None:
    if mbid:
        hit = next((s for s in await _search_songs(client, mbid) if s.mbid == mbid), None)
        if hit is not None:
            return MatchResult(song_id=hit.id, confidence=1.0, method="mbid", song=hit)

    seen: dict[str, Song] = {}
    best: tuple[Song, float] | None = None
    queries = (_search_query(_first_credit(artist) or artist, title), _search_query(title))
    for query in dict.fromkeys(queries):  # dedupe, keep order
        fresh = [s for s in await _search_songs(client, query) if s.id not in seen]
        seen.update((s.id, s) for s in fresh)
        cand = best_candidate(artist, title, fresh, mbid)
        if cand and (best is None or cand[1] > best[1]):
            best = cand
        if best and best[1] >= threshold:
            break
    if best is None or best[1] < threshold:
        log.debug(
            "match.miss", artist=artist, title=title, best=round(best[1], 3) if best else None
        )
        return None
    song, conf = best
    method = "mbid" if conf == 1.0 and mbid else "search"
    return MatchResult(song_id=song.id, confidence=conf, method=method, song=song)


async def _match_one(
    client: SubsonicClient,
    ref: TrackRef,
    cached: tuple[str, float] | None,
    threshold: float,
) -> tuple[MatchResult | None, bool]:
    """→ (result, cached entry was stale)."""
    stale = False
    if cached is not None:
        song_id, conf = cached
        try:
            song = await client.song(song_id)
        except SubsonicNotFound:
            stale = True
        else:
            return MatchResult(song_id=song_id, confidence=conf, method="cache", song=song), False
    return await _search_match(client, ref.artist, ref.title, ref.mbid, threshold), stale


async def match_tracks(
    client: SubsonicClient,
    refs: Sequence[TrackRef],
    *,
    cache: MatchCache | None = None,
    threshold: float = MATCH_THRESHOLD,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> list[MatchResult | None]:
    """Match many tracks (results in input order); one cache read + one write per batch."""
    if not refs:
        return []
    keys = [track_key(r.artist, r.title) for r in refs]
    cached = await asyncio.to_thread(cache.get_many, keys) if cache else {}
    sem = asyncio.Semaphore(max(1, concurrency))

    async def run(ref: TrackRef, key: str) -> tuple[MatchResult | None, bool]:
        async with sem:
            return await _match_one(client, ref, cached.get(key), threshold)

    outcomes = await asyncio.gather(*(run(r, k) for r, k in zip(refs, keys, strict=True)))
    results = [res for res, _ in outcomes]

    if cache is not None:
        stale = [k for k, (_, was_stale) in zip(keys, outcomes, strict=True) if was_stale]
        fresh = [
            (k, r.artist, r.title, res.song_id, res.confidence)
            for k, r, res in zip(keys, refs, results, strict=True)
            if res is not None and res.method != "cache"
        ]
        if stale:
            await asyncio.to_thread(cache.forget, stale)
        if fresh:
            await asyncio.to_thread(cache.put_many, fresh)

    log.info(
        "match.batch",
        n=len(refs),
        matched=sum(r is not None for r in results),
        cache_hits=sum(r is not None and r.method == "cache" for r in results),
    )
    return results


async def match_track(
    client: SubsonicClient,
    artist: str,
    title: str,
    mbid: str = "",
    *,
    cache: MatchCache | None = None,
    threshold: float = MATCH_THRESHOLD,
) -> MatchResult | None:
    """Best library song for one track, or None below ``threshold``."""
    ref = TrackRef(artist=artist, title=title, mbid=mbid or "")
    return (await match_tracks(client, [ref], cache=cache, threshold=threshold))[0]
