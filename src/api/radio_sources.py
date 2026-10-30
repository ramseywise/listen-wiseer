"""Blocking candidate sources behind ``/api/radio`` and ``/api/discover`` — open-world
similarity (``recommend.discover``), the closed-world archive corpus (``recommend.engine``)
and legal free downloads (``library.downloads``). Routes call them via ``asyncio.to_thread``;
tests replace the whole object (``RadioSources``).

Every source fails soft: a missing key / unreachable API / untrained model → fewer picks.
"""

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from typing import TYPE_CHECKING, Literal, Protocol, TypeVar

import duckdb

from api.deps import DbConnect
from etl.db import fetch_one
from library.downloads import find_free
from recommend.discover import History, rank, source_calls
from sources import deezer
from sources.schemas import FreeTrack, SimilarItem, TrackRef
from utils.exceptions import SourceError
from utils.logging import get_logger

if TYPE_CHECKING:
    from recommend.engine import RecommendationEngine

log = get_logger(__name__)

T = TypeVar("T")

EXPAND_ARTISTS = 6  # similar artists whose top Deezer tracks fill in when track-level is short
EXPAND_TRACKS = 2
_SOURCE_LABELS = {"lastfm": "Last.fm", "listenbrainz": "ListenBrainz", "deezer": "Deezer"}


class Pick(TrackRef):
    """A candidate track with why it was picked."""

    origin: Literal["corpus", "discover"]
    reason: str = ""
    known_artist: bool = False
    n_plays: int = 0


class RadioSources(Protocol):
    def similar(
        self,
        artist: str,
        title: str | None,
        *,
        history: History,
        n: int,
        new_artist_ratio: float,
        timeout: float,
    ) -> list[Pick]: ...

    def corpus(self, artist: str, title: str, *, k: int) -> list[Pick]: ...

    def free(self, artist: str, *, limit: int) -> list[FreeTrack]: ...


def run_parallel(
    calls: list[tuple[str, Callable[[], T]]], *, timeout: float, workers: int = 4
) -> list[tuple[str, T]]:
    """Run blocking calls in threads; return the ones done (without error) within ``timeout``.
    Stragglers keep running in the background until their own HTTP timeout."""
    if not calls:
        return []
    pool = ThreadPoolExecutor(max_workers=min(workers, len(calls)), thread_name_prefix="radio")
    futures = {pool.submit(call): name for name, call in calls}
    done, pending = wait(futures, timeout=timeout)
    pool.shutdown(wait=False, cancel_futures=True)
    out: list[tuple[str, T]] = []
    for fut in done:
        name = futures[fut]
        try:
            out.append((name, fut.result()))
        except (SourceError, duckdb.Error) as exc:
            log.warning("radio.source_failed", source=name, error=str(exc))
    for fut in pending:
        log.warning("radio.source_timeout", source=futures[fut], timeout_s=timeout)
    order = {name: i for i, (name, _) in enumerate(calls)}
    return sorted(out, key=lambda r: order[r[0]])


def _reason(sources: list[str]) -> str:
    names = [_SOURCE_LABELS.get(s, s) for s in sources]
    return f"Similar on {' + '.join(names)}" if names else ""


def _expand_artists(
    items: list[SimilarItem], seed_artist: str, have: set[str], n: int
) -> list[Pick]:
    """Top Deezer tracks of the best artist-level matches (Deezer related / Last.fm similar
    artists carry no titles, so without Last.fm or ListenBrainz they'd rank nothing)."""
    best: dict[str, float] = {}
    names: dict[str, str] = {}
    for it in items:
        if it.title or not it.artist:
            continue
        key = it.artist.casefold()
        if key not in have:
            best[key] = max(best.get(key, 0.0), it.match)
            names.setdefault(key, it.artist)
    artists = sorted(best, key=lambda k: -best[k])[: max(1, min(EXPAND_ARTISTS, n))]
    out: list[Pick] = []
    for key in artists:
        try:
            hits = deezer.search_tracks(names[key], limit=EXPAND_TRACKS * 4)
        except SourceError as exc:
            log.warning("radio.expand_failed", artist=names[key], error=str(exc))
            continue
        same = [h for h in hits if h.get("artist", {}).get("name", "").casefold() == key]
        out += [
            Pick(
                artist=h["artist"]["name"],
                title=h.get("title", ""),
                origin="discover",
                reason=f"Related to {seed_artist} on Deezer",
            )
            for h in same[:EXPAND_TRACKS]
            if h.get("title")
        ]
        if len(out) >= n:
            break
    return out


class LiveSources:
    """The real sources. ``db_connect`` is the API's short-lived DuckDB connection factory."""

    def __init__(self, db_connect: DbConnect):
        self._connect = db_connect
        self._engine: RecommendationEngine | None = None
        self._engine_failed = False
        self._engine_lock = threading.Lock()

    # ── Open world ───────────────────────────────────────────────────────────

    def similar(
        self,
        artist: str,
        title: str | None,
        *,
        history: History,
        n: int,
        new_artist_ratio: float = 0.5,
        timeout: float = 10.0,
    ) -> list[Pick]:
        started = time.monotonic()
        results = run_parallel(source_calls(artist, title), timeout=timeout)
        items = [it for _, got in results for it in got]
        ranked = rank(
            items,
            history,
            seed_artist=artist,
            seed_title=title,
            n=n,
            new_artist_ratio=new_artist_ratio,
        )
        picks = [
            Pick(
                artist=c.artist,
                title=c.title,
                mbid=c.mbid,
                origin="discover",
                reason=_reason(c.sources),
                known_artist=c.known_artist,
                n_plays=c.n_plays,
            )
            for c in ranked
        ]
        left = timeout - (time.monotonic() - started)
        if len(picks) < n and left > 1.0:
            have = {p.artist.casefold() for p in picks} | {artist.casefold()}
            expand = run_parallel(
                [
                    (
                        "deezer.top_tracks",
                        lambda: _expand_artists(items, artist, have, n - len(picks)),
                    )
                ],
                timeout=left,
            )
            known = history.known_artists
            picks += [
                p.model_copy(update={"known_artist": p.artist.strip().lower() in known})
                for _, got in expand
                for p in got
            ]
        log.info(
            "radio.similar",
            seed=artist,
            sources=[name for name, _ in results],
            n_items=len(items),
            n_out=len(picks),
        )
        return picks

    def free(self, artist: str, *, limit: int) -> list[FreeTrack]:
        return find_free(artist, limit=limit)

    # ── Closed world (archive corpus) ────────────────────────────────────────

    def _load_engine(self) -> "RecommendationEngine | None":
        with self._engine_lock:
            if self._engine is not None or self._engine_failed:
                return self._engine
            from paths import DATA_DIR, MODELS_DIR  # noqa: PLC0415 — heavy, load on first use
            from recommend.engine import RecommendationEngine  # noqa: PLC0415

            try:
                self._engine = RecommendationEngine(models_dir=MODELS_DIR, data_dir=DATA_DIR)
            except FileNotFoundError as exc:  # models not trained — don't retry
                self._engine_failed = True
                log.warning("radio.engine_unavailable", error=str(exc))
            except duckdb.Error as exc:  # DB busy — retry on the next request
                log.warning("radio.engine_load_failed", error=str(exc))
            return self._engine

    def corpus(self, artist: str, title: str, *, k: int) -> list[Pick]:
        conn = self._connect()
        try:
            row = fetch_one(conn, _SEED_SQL, [title, artist, title, artist])
        finally:
            conn.close()
        if row is None:
            return []
        engine = self._load_engine()
        if engine is None:
            return []
        from recommend.schemas import RecommendRequest  # noqa: PLC0415

        result = engine.recommend(RecommendRequest(request_type="track", seed_id=row[0], k=k))
        if not result.track_ids:
            return []
        conn = self._connect()
        try:
            rows = conn.execute(_NAMES_SQL, [result.track_ids]).fetchall()
        finally:
            conn.close()
        named = {tid: (a, t) for tid, a, t in rows if a and t}
        return [
            Pick(artist=a, title=t, origin="corpus", reason="Sounds like it (your archive)")
            for a, t in (named[tid] for tid in result.track_ids if tid in named)
        ]


_SEED_SQL = """
SELECT t.track_id FROM tracks t
JOIN track_artists USING (track_id) JOIN artists a USING (artist_id)
WHERE lower(t.track_name) = lower(?) AND lower(a.artist_name) = lower(?)
UNION ALL
SELECT track_id FROM external_tracks
WHERE lower(track_name) = lower(?) AND artist_names ILIKE '%' || ? || '%'
LIMIT 1
"""

# First credited artist = track_artists insertion order (Spotify's credit order).
_NAMES_SQL = """
SELECT t.track_id, arg_min(a.artist_name, ta.rowid), any_value(t.track_name)
FROM tracks t JOIN track_artists ta USING (track_id) JOIN artists a USING (artist_id)
WHERE list_contains(?, t.track_id)
GROUP BY t.track_id
"""
