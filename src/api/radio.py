"""Radio + Discover.

``GET /api/radio`` — tracks like a seed song / artist for the endless queue: open-world
candidates (``recommend.discover``), plus the archive corpus model when the seed is in it,
library matches first, ≤2 per artist, minus what the queue already holds (``exclude``).

``GET /api/discover`` — sections for the Discover page: library songs not played yet, new
artists around recent plays / likes / top archive artists, and free legal downloads.

External sources are slow and rate-limited: every blocking call runs in a worker thread
under a deadline, and a route past its deadline returns what it has. Non-library tracks
carry no ``playable`` — the web resolves them lazily via ``/api/playable``.
"""

import asyncio
import time
from collections import defaultdict
from collections.abc import Awaitable, Iterable, Sequence
from typing import Annotated, Literal, TypeVar
from urllib.parse import unquote

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from api.deps import Db, DbConnect, Subsonic
from api.playable import Cache, Playable, cover_url
from api.radio_sources import LiveSources, Pick, RadioSources, run_parallel
from etl.history import track_key
from etl.resolve import MIN_MS_PLAYED
from library.match import MatchCache, MatchResult, match_tracks, primary_artist
from recommend.discover import History, load_history
from sources.schemas import FreeTrack
from sources.subsonic import Song, SubsonicClient
from utils.exceptions import SourceError
from utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["radio"])

T = TypeVar("T")

MAX_PER_ARTIST = 2
RADIO_TIMEOUT_S = 12.0
DISCOVER_TIMEOUT_S = 20.0
DISCOVER_TTL_S = 300.0
DISCOVER_PARTIAL_TTL_S = 60.0  # a page cut short by a slow source is retried sooner
SECTION_SIZE = 15
NEW_SEEDS = 3
FREE_ARTISTS = 4
LOW_PLAYS = 1  # "not played yet" = fewer real plays than this + 1


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class FreeDownload(_Model):
    source: str  # jamendo | archive_org
    download_url: str
    page_url: str | None = None
    license_url: str | None = None


class RadioTrack(_Model):
    artist: str
    title: str
    mbid: str | None = None
    source: Literal["library", "corpus", "discover"]
    reason: str | None = None
    playable: Playable | None = None
    free: FreeDownload | None = None


class DiscoverSection(_Model):
    id: str
    title: str
    tracks: list[RadioTrack]


class DiscoverPage(_Model):
    sections: list[DiscoverSection]


# ── Dependencies ─────────────────────────────────────────────────────────────


def get_radio_sources(request: Request) -> RadioSources:
    sources = getattr(request.app.state, "radio_sources", None)
    if sources is None:
        sources = LiveSources(request.app.state.db_connect)
        request.app.state.radio_sources = sources
    return sources


Sources = Annotated[RadioSources, Depends(get_radio_sources)]


# ── Helpers ──────────────────────────────────────────────────────────────────


def song_playable(song: Song) -> Playable:
    return Playable(
        artist=song.artist,
        title=song.title,
        song_id=song.id,
        cover_url=cover_url(song.cover_art),
        song=song,
    )


def parse_exclude(raw: str) -> tuple[set[str], set[str]]:
    """``artist::title`` keys (components may be percent-encoded, so names can hold commas)
    and bare song ids → (track keys, song ids)."""
    keys: set[str] = set()
    ids: set[str] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if "::" in token:
            artist, _, title = token.partition("::")
            keys.add(track_key(unquote(artist), unquote(title)))
        else:
            ids.add(unquote(token))
    return keys, ids


async def _bounded(aw: Awaitable[T], timeout: float, default: T, what: str) -> T:
    try:
        return await asyncio.wait_for(aw, timeout=max(timeout, 0.01))
    except TimeoutError:
        log.warning("api.radio.timeout", step=what, timeout_s=round(timeout, 1))
        return default


def _history(connect: DbConnect) -> History:
    try:
        conn = connect()
        try:
            return load_history(conn)
        finally:
            conn.close()
    except duckdb.Error as exc:
        log.warning("api.radio.history_unavailable", error=str(exc))
        return History()


async def _match(
    client: SubsonicClient, picks: Sequence[Pick], cache: MatchCache | None
) -> list[MatchResult | None]:
    try:
        return await match_tracks(client, picks, cache=cache)
    except SourceError as exc:  # Navidrome down → nothing is in the library
        log.warning("api.radio.match_failed", n=len(picks), error=str(exc))
        return [None] * len(picks)


def _cap_per_artist(tracks: Iterable[RadioTrack], n: int) -> list[RadioTrack]:
    per: dict[str, int] = defaultdict(int)
    out: list[RadioTrack] = []
    for t in tracks:
        a = primary_artist(t.artist) or t.artist.casefold()
        if per[a] >= MAX_PER_ARTIST:
            continue
        per[a] += 1
        out.append(t)
        if len(out) >= n:
            break
    return out


def _interleave(*lists: Sequence[Pick]) -> list[Pick]:
    out: list[Pick] = []
    for i in range(max((len(x) for x in lists), default=0)):
        out += [x[i] for x in lists if i < len(x)]
    return out


async def _rank_picks(
    client: SubsonicClient,
    picks: Sequence[Pick],
    *,
    cache: MatchCache | None,
    exclude_keys: set[str],
    exclude_ids: set[str],
    limit: int,
    timeout: float,
) -> list[RadioTrack]:
    """Dedupe + exclude → library match → library hits first → ≤2 per artist."""
    seen = set(exclude_keys)
    fresh: list[Pick] = []
    for p in picks:
        key = track_key(p.artist, p.title)
        if key not in seen and p.artist and p.title:
            seen.add(key)
            fresh.append(p)
    fresh = fresh[: limit * 3]  # bounds the search3 calls
    hits = await _bounded(_match(client, fresh, cache), timeout, [None] * len(fresh), "match")
    library: list[RadioTrack] = []
    rest: list[RadioTrack] = []
    for p, hit in zip(fresh, hits, strict=True):
        if hit is not None and hit.song_id in exclude_ids:
            continue
        track = RadioTrack(
            artist=p.artist,
            title=p.title,
            mbid=p.mbid or None,
            source="library" if hit else p.origin,
            reason=p.reason or None,
            playable=(
                song_playable(hit.song)
                if hit.song
                else Playable(artist=p.artist, title=p.title, song_id=hit.song_id)
            )
            if hit
            else None,
        )
        (library if hit else rest).append(track)
    return _cap_per_artist([*library, *rest], limit)


# ── /api/radio ───────────────────────────────────────────────────────────────


@router.get("/radio", response_model=list[RadioTrack], response_model_exclude_none=True)
async def radio(
    client: Subsonic,
    db: Db,
    cache: Cache,
    sources: Sources,
    song_id: Annotated[str, Query(alias="songId")] = "",
    artist: str = "",
    title: str = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    exclude: str = "",
) -> list[RadioTrack]:
    started = time.monotonic()
    exclude_keys, exclude_ids = parse_exclude(exclude)
    if song_id:
        song = await client.song(song_id)  # 404 when unknown
        artist, title = song.artist, song.title
        exclude_ids.add(song.id)
    artist, title = artist.strip(), title.strip()
    if not artist:
        raise HTTPException(422, "songId or artist is required")
    if title:
        exclude_keys.add(track_key(artist, title))

    history = await asyncio.to_thread(_history, db)
    budget = RADIO_TIMEOUT_S * 0.7
    similar_task = asyncio.to_thread(
        sources.similar,
        artist,
        title or None,
        history=history,
        n=limit * 2,
        new_artist_ratio=0.5,
        timeout=budget - 1.0,
    )
    corpus_task = (
        asyncio.to_thread(sources.corpus, artist, title, k=limit)
        if title
        else asyncio.sleep(0, result=[])
    )
    similar, corpus = await asyncio.gather(
        _bounded(similar_task, budget, [], "similar"),
        _bounded(_safe(corpus_task, "corpus"), budget, [], "corpus"),
    )
    left = RADIO_TIMEOUT_S - (time.monotonic() - started)
    tracks = await _rank_picks(
        client,
        _interleave(similar, corpus),
        cache=cache,
        exclude_keys=exclude_keys,
        exclude_ids=exclude_ids,
        limit=limit,
        timeout=left,
    )
    log.info(
        "api.radio.done",
        seed=artist,
        n_similar=len(similar),
        n_corpus=len(corpus),
        n_out=len(tracks),
        n_library=sum(t.source == "library" for t in tracks),
        ms=round((time.monotonic() - started) * 1000),
    )
    return tracks


async def _safe(aw: Awaitable[list[T]], what: str) -> list[T]:
    """A failing optional source (corpus model, DB busy) contributes nothing."""
    try:
        return await aw
    except (SourceError, duckdb.Error, OSError, ValueError) as exc:
        log.warning("api.radio.source_failed", source=what, error=str(exc))
        return []


# ── /api/discover ────────────────────────────────────────────────────────────

_PLAYS_SQL = """
SELECT navidrome_id, track_key, count(*) FILTER (WHERE coalesce(ms_played, 0) >= ?)
FROM plays GROUP BY ALL
"""

_RECENT_ARTISTS_SQL = """
SELECT artist_name FROM plays
WHERE artist_name IS NOT NULL AND coalesce(ms_played, 0) >= ?
GROUP BY artist_name ORDER BY max(ts) DESC LIMIT ?
"""

_TOP_ARCHIVE_ARTISTS_SQL = """
SELECT a.artist_name FROM playlist_tracks pt
JOIN track_artists ta USING (track_id) JOIN artists a USING (artist_id)
WHERE pt.removed_at IS NULL AND a.artist_name IS NOT NULL
GROUP BY a.artist_name ORDER BY count(*) DESC, a.artist_name LIMIT ?
"""


def _play_counts(connect: DbConnect) -> tuple[dict[str, int], dict[str, int]]:
    """Real plays by Navidrome id and by track key."""
    by_id: dict[str, int] = defaultdict(int)
    by_key: dict[str, int] = defaultdict(int)
    try:
        conn = connect()
        try:
            rows = conn.execute(_PLAYS_SQL, [MIN_MS_PLAYED]).fetchall()
        finally:
            conn.close()
    except duckdb.Error as exc:
        log.warning("api.discover.plays_unavailable", error=str(exc))
        return {}, {}
    for nid, key, n in rows:
        if nid:
            by_id[nid] += n
        if key:
            by_key[key] += n
    return by_id, by_key


def _seed_artists(connect: DbConnect, n: int) -> tuple[list[str], str]:
    """Recently played artists, else the archive's most-playlisted ones."""
    try:
        conn = connect()
        try:
            recent = [
                r[0] for r in conn.execute(_RECENT_ARTISTS_SQL, [MIN_MS_PLAYED, n]).fetchall()
            ]
            if recent:
                return recent, "plays"
            top = [r[0] for r in conn.execute(_TOP_ARCHIVE_ARTISTS_SQL, [n]).fetchall()]
            return top, "archive"
        finally:
            conn.close()
    except duckdb.Error as exc:
        log.warning("api.discover.seeds_unavailable", error=str(exc))
        return [], "none"


async def _unplayed(client: SubsonicClient, db: DbConnect) -> list[RadioTrack]:
    try:
        page = await client.album_list("random", size=SECTION_SIZE)
        albums = await asyncio.gather(*(client.album(a.id) for a in page.albums))
    except SourceError as exc:
        log.warning("api.discover.library_unavailable", error=str(exc))
        return []
    by_id, by_key = await asyncio.to_thread(_play_counts, db)
    tracks: list[RadioTrack] = []
    for album in albums:
        for song in album.songs:
            n = max(by_id.get(song.id, 0), by_key.get(track_key(song.artist, song.title), 0))
            if n >= LOW_PLAYS:
                continue
            tracks.append(
                RadioTrack(
                    artist=song.artist,
                    title=song.title,
                    mbid=song.mbid,
                    source="library",
                    reason="Never played",
                    playable=song_playable(song),
                )
            )
    return _cap_per_artist(tracks, SECTION_SIZE)


async def _starred_artists(client: SubsonicClient, n: int) -> list[str]:
    try:
        songs = await client.starred_songs()
    except SourceError:
        return []
    return list(dict.fromkeys(s.artist for s in songs if s.artist))[:n]


async def _new_to_you(
    client: SubsonicClient,
    db: DbConnect,
    cache: MatchCache | None,
    sources: RadioSources,
    timeout: float,
) -> tuple[list[RadioTrack], list[str]]:
    """→ (tracks, seed artists)."""
    started = time.monotonic()
    seeds, origin = await asyncio.to_thread(_seed_artists, db, NEW_SEEDS)
    if origin != "plays":
        starred = await _starred_artists(client, NEW_SEEDS)
        if starred:
            seeds, origin = starred, "starred"
    if not seeds:
        return [], []
    history = await asyncio.to_thread(_history, db)
    per_seed = await asyncio.to_thread(
        run_parallel,
        [
            (
                seed,
                lambda seed=seed: sources.similar(
                    seed,
                    None,
                    history=history,
                    n=SECTION_SIZE,
                    new_artist_ratio=1.0,
                    timeout=timeout * 0.6,
                ),
            )
            for seed in seeds
        ],
        timeout=timeout * 0.7,
        workers=len(seeds),
    )
    seed_keys = {s.casefold() for s in seeds}
    picks = _interleave(
        *[
            [
                p
                for p in got
                if not p.known_artist and p.n_plays == 0 and p.artist.casefold() not in seed_keys
            ]
            for _, got in per_seed
        ]
    )
    left = timeout - (time.monotonic() - started)
    tracks = await _rank_picks(
        client,
        picks,
        cache=cache,
        exclude_keys=set(),
        exclude_ids=set(),
        limit=SECTION_SIZE,
        timeout=left,
    )
    log.info("api.discover.new", seeds=seeds, seed_origin=origin, n_out=len(tracks))
    return tracks, seeds


def _free_track(t: FreeTrack) -> RadioTrack:
    label = "Jamendo (CC)" if t.source == "jamendo" else "Internet Archive"
    return RadioTrack(
        artist=t.artist,
        title=t.title,
        source="discover",
        reason=f"Free on {label}",
        free=FreeDownload(
            source=t.source,
            download_url=t.download_url,
            page_url=t.page_url or None,
            license_url=t.license_url or None,
        ),
    )


async def _free(sources: RadioSources, artists: list[str], timeout: float) -> list[RadioTrack]:
    if not artists or timeout <= 0.5:
        return []
    results = await asyncio.to_thread(
        run_parallel,
        [(a, lambda a=a: sources.free(a, limit=MAX_PER_ARTIST)) for a in artists],
        timeout=timeout,
        workers=2,  # archive.org + Jamendo are shared, unauthenticated quotas
    )
    seen: set[str] = set()
    out: list[RadioTrack] = []
    for _, got in results:
        for t in got:
            key = track_key(t.artist, t.title)
            if key not in seen:
                seen.add(key)
                out.append(_free_track(t))
    return _cap_per_artist(out, SECTION_SIZE)


async def build_discover(
    client: SubsonicClient, db: DbConnect, cache: MatchCache | None, sources: RadioSources
) -> tuple[DiscoverPage, bool]:
    """→ (page, complete). Not complete = some step ran out of time."""
    started = time.monotonic()
    budget = DISCOVER_TIMEOUT_S
    unplayed_task = asyncio.create_task(_unplayed(client, db))
    new, seeds = await _bounded(
        _new_to_you(client, db, cache, sources, timeout=budget * 0.6),
        budget * 0.65,
        ([], []),
        "new_to_you",
    )
    complete = bool(seeds) or not new
    free_artists = list(dict.fromkeys(t.artist for t in new))[:FREE_ARTISTS] or seeds
    left = budget - (time.monotonic() - started)
    free = await _bounded(_free(sources, free_artists, left - 1.0), left, [], "free")
    unplayed = await _bounded(unplayed_task, budget - (time.monotonic() - started), [], "unplayed")
    complete = complete and time.monotonic() - started < budget
    page = DiscoverPage(
        sections=[
            DiscoverSection(
                id="unplayed", title="In your library, not played yet", tracks=unplayed
            ),
            DiscoverSection(id="new", title="New to you", tracks=new),
            DiscoverSection(id="free", title="Free to download", tracks=free),
        ]
    )
    log.info(
        "api.discover.done",
        n_unplayed=len(unplayed),
        n_new=len(new),
        n_free=len(free),
        ms=round((time.monotonic() - started) * 1000),
    )
    return page, complete


@router.get("/discover", response_model=DiscoverPage, response_model_exclude_none=True)
async def discover_page(
    request: Request,
    client: Subsonic,
    db: Db,
    cache: Cache,
    sources: Sources,
    refresh: bool = False,
) -> DiscoverPage:
    state = request.app.state
    lock: asyncio.Lock = getattr(state, "discover_lock", None) or asyncio.Lock()
    state.discover_lock = lock
    async with lock:  # one build at a time; waiters get the fresh cache
        cached: tuple[float, DiscoverPage] | None = getattr(state, "discover_cache", None)
        if cached and not refresh and time.monotonic() < cached[0]:
            return cached[1]
        page, complete = await build_discover(client, db, cache, sources)
        ttl = DISCOVER_TTL_S if complete else DISCOVER_PARTIAL_TTL_S
        state.discover_cache = (time.monotonic() + ttl, page)
        return page
