"""Unit tests for library.match — normalisation, scoring, search + cache over a fake Navidrome."""

from collections.abc import Callable
from pathlib import Path

import duckdb
import httpx
import pytest

from etl.db import init_schema
from library.match import (
    MATCH_THRESHOLD,
    DuckDBMatchCache,
    match_track,
    match_tracks,
    normalize_artist,
    normalize_title,
    primary_artist,
    score,
)
from sources.schemas import TrackRef
from sources.subsonic import Song, SubsonicClient, SubsonicUnavailable

MBID = "0f3c5b41-0000-4000-8000-000000000001"


def _song(sid: str, title: str, artist: str, mbid: str = "") -> dict:
    return {"id": sid, "title": title, "artist": artist, "album": "A", "musicBrainzId": mbid}


LIBRARY = [
    _song("s1", "April Showers", "ProleteR", MBID),
    _song("s2", "Talk to me", "Miranda Shvangiradze"),
    _song("s3", "Downtown Irony", "ProleteR"),
    _song("s4", "Weird Fishes / Arpeggi", "Radiohead"),
]


def _ok(**body) -> httpx.Response:
    return httpx.Response(200, json={"subsonic-response": {"status": "ok", **body}})


def _failed(code: int) -> httpx.Response:
    err = {"code": code, "message": "x"}
    return httpx.Response(200, json={"subsonic-response": {"status": "failed", "error": err}})


def _navidrome(songs: list[dict], queries: list[str]) -> Callable[[httpx.Request], httpx.Response]:
    """search3 = every query word appears in title / artist / mbid (like Navidrome's full text)."""

    def handler(request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.removeprefix("/rest/")
        q = request.url.params
        if endpoint == "search3":
            queries.append(q["query"])
            words = q["query"].lower().split()
            hits = [
                s
                for s in songs
                if all(
                    w in f"{s['title']} {s['artist']} {s['musicBrainzId']}".lower() for w in words
                )
            ]
            return _ok(searchResult3={"song": hits})
        if endpoint == "getSong":
            song = next((s for s in songs if s["id"] == q["id"]), None)
            return _ok(song=song) if song else _failed(70)
        return _failed(0)

    return handler


@pytest.fixture
def queries() -> list[str]:
    return []


@pytest.fixture
def client(queries: list[str]) -> SubsonicClient:
    return SubsonicClient(
        "http://nd.test", "me", "pw", transport=httpx.MockTransport(_navidrome(LIBRARY, queries))
    )


@pytest.fixture
def cache(tmp_path: Path) -> DuckDBMatchCache:
    db = tmp_path / "xref.db"
    return DuckDBMatchCache(lambda: duckdb.connect(str(db)))


# ── Normalisation ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Weird Fishes / Arpeggi", "weird fishes arpeggi"),
        ("Here Comes the Sun - Remastered 2009", "here comes the sun"),
        ("Here Comes the Sun - 2019 Mix", "here comes the sun 2019 mix"),  # mixes are kept
        ("Wonderwall (Remastered)", "wonderwall"),
        ("Creep (Live at Glastonbury)", "creep"),
        ("Paranoid Android - Live", "paranoid android"),
        ("Live Forever", "live forever"),  # leading 'live' is part of the title
        ("Song (feat. Someone)", "song"),
        ("Song [ft. A & B]", "song"),
        ("Song feat. Someone Else", "song"),
        ("Song (with Friend)", "song"),
        ("Song (Remix)", "song remix"),  # remixes are different recordings
        ("Don’t Stop Me Now", "dont stop me now"),
        ("Café  Del   Mar", "cafe del mar"),
        ("Rock & Roll", "rock and roll"),
        ("1999 (Mono) [Bonus Track]", "1999"),
    ],
)
def test_normalize_title(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("The Beatles", "beatles"),
        ("Beyoncé", "beyonce"),
        ("ProleteR feat. Someone", "proleter"),
        ("The The", "the"),
        ("Simon & Garfunkel", "simon and garfunkel"),
    ],
)
def test_normalize_artist(raw: str, expected: str) -> None:
    assert normalize_artist(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("A & B", "a"), ("Daft Punk, Pharrell", "daft punk"), ("X ft. Y", "x"), ("Solo", "solo")],
)
def test_primary_artist(raw: str, expected: str) -> None:
    assert primary_artist(raw) == expected


# ── Scoring ──────────────────────────────────────────────────────────────────


def _s(title: str, artist: str, mbid: str | None = None) -> Song:
    return Song(id="x", title=title, artist=artist, mbid=mbid)


def test_score_exact_and_normalised_variants_pass() -> None:
    assert score("Radiohead", "Creep", _s("Creep", "Radiohead")) == 1.0
    assert score("The Beatles", "Something - 2019 Remaster", _s("Something", "Beatles")) == 1.0
    assert score("Daft Punk & Pharrell", "Get Lucky", _s("Get Lucky", "Daft Punk")) >= (
        MATCH_THRESHOLD
    )


def test_score_mbid_equal_wins_even_with_different_text() -> None:
    assert score("Someone", "Other", _s("April Showers", "ProleteR", MBID), MBID) == 1.0


@pytest.mark.parametrize(
    ("artist", "title", "song"),
    [
        ("Radiohead", "Creep", _s("Creep", "Stone Temple Pilots")),  # same title, other artist
        ("Radiohead", "Reckoner", _s("Creep", "Radiohead")),  # same artist, other song
        ("Radiohead", "Creep", _s("Creep (Acoustic Remix)", "Radiohead")),
    ],
)
def test_score_rejects_wrong_song(artist: str, title: str, song: Song) -> None:
    assert score(artist, title, song) < MATCH_THRESHOLD


# ── match_track ──────────────────────────────────────────────────────────────


async def test_match_by_search(client: SubsonicClient) -> None:
    res = await match_track(client, "ProleteR", "Downtown Irony (Remastered)")
    assert res is not None
    assert (res.song_id, res.method) == ("s3", "search")
    assert res.song is not None and res.song.title == "Downtown Irony"
    assert res.confidence >= MATCH_THRESHOLD


async def test_match_by_mbid_first(client: SubsonicClient, queries: list[str]) -> None:
    res = await match_track(client, "Wrong Artist", "Wrong Title", MBID)
    assert res is not None
    assert (res.song_id, res.method, res.confidence) == ("s1", "mbid", 1.0)
    assert queries == [MBID]


async def test_match_falls_back_to_title_only_search(
    client: SubsonicClient, queries: list[str]
) -> None:
    # artist tagged differently in the library → artist+title search misses, title-only hits
    res = await match_track(client, "Miranda Shvangiradze feat. Nobody", "Talk To Me")
    assert res is not None and res.song_id == "s2"
    res = await match_track(client, "Mirandda Shvangiradze", "Talk to me")
    assert res is not None and res.song_id == "s2"
    assert queries[-2:] == ["Mirandda Shvangiradze Talk to me", "Talk to me"]


async def test_no_match_returns_none(client: SubsonicClient) -> None:
    assert await match_track(client, "Radiohead", "Reckoner") is None
    assert await match_track(client, "Someone Else", "April Showers") is None


async def test_navidrome_down_raises() -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = SubsonicClient("http://nd.test", "me", "pw", transport=httpx.MockTransport(refused))
    with pytest.raises(SubsonicUnavailable):
        await match_track(client, "ProleteR", "April Showers")


# ── Cache ────────────────────────────────────────────────────────────────────


async def test_cache_stores_hits_not_misses(
    client: SubsonicClient, cache: DuckDBMatchCache, queries: list[str]
) -> None:
    refs = [
        TrackRef(artist="ProleteR", title="April Showers"),
        TrackRef(artist="Radiohead", title="Reckoner"),
    ]
    first = await match_tracks(client, refs, cache=cache)
    assert [r.song_id if r else None for r in first] == ["s1", None]
    n_queries = len(queries)

    second = await match_tracks(client, refs, cache=cache)
    assert second[0] is not None and second[0].method == "cache"
    assert second[0].song is not None and second[0].song.id == "s1"
    assert second[1] is None
    # the cached hit costs a getSong, not a search; the miss is searched again
    assert all("April" not in q for q in queries[n_queries:])
    assert any("Reckoner" in q for q in queries[n_queries:])


async def test_stale_cache_entry_is_rematched(queries: list[str], cache: DuckDBMatchCache) -> None:
    cache.put_many([("proleter\tapril showers", "ProleteR", "April Showers", "gone", 0.9)])
    client = SubsonicClient(
        "http://nd.test", "me", "pw", transport=httpx.MockTransport(_navidrome(LIBRARY, queries))
    )
    res = await match_track(client, "ProleteR", "April Showers", cache=cache)
    assert res is not None and (res.song_id, res.method) == ("s1", "search")
    assert cache.get_many(["proleter\tapril showers"]) == {
        "proleter\tapril showers": ("s1", res.confidence)
    }


def test_cache_keeps_mb_columns_and_resolve_still_sees_row_as_pending(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    cache = DuckDBMatchCache(lambda: duckdb.connect(str(db)))
    with duckdb.connect(str(db)) as conn:
        init_schema(conn)
        conn.execute(
            "INSERT INTO track_xref (track_key, mbid, resolved_at) VALUES ('a\tb', 'm1', now())"
        )
    cache.put_many([("a\tb", "A", "B", "s9", 0.95), ("c\td", "C", "D", "s8", 0.9)])
    with duckdb.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT track_key, mbid, navidrome_id, resolved_at IS NULL FROM track_xref ORDER BY 1"
        ).fetchall()
    assert rows == [("a\tb", "m1", "s9", False), ("c\td", None, "s8", True)]


def test_cache_fails_soft(tmp_path: Path) -> None:
    def broken() -> duckdb.DuckDBPyConnection:
        raise duckdb.IOException("locked")

    cache = DuckDBMatchCache(broken)
    assert cache.get_many(["k"]) == {}
    cache.put_many([("k", "a", "t", "s", 1.0)])  # no raise
    cache.forget(["k"])
