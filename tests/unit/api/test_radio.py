"""``/api/radio`` + ``/api/discover`` — sources faked, fake Navidrome, tmp DuckDB."""

import time
from datetime import datetime
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from api import radio
from api.playable import get_match_cache
from api.radio import get_radio_sources, parse_exclude
from api.radio_sources import Pick, run_parallel
from etl.history import track_key
from recommend.discover import History
from sources.schemas import FreeTrack
from tests.unit.api.conftest import FakeNavidrome, connect_to, refused
from utils.exceptions import SourceError


class FakeSources:
    def __init__(
        self,
        similar: list[Pick] | None = None,
        corpus: list[Pick] | None = None,
        free: dict[str, list[FreeTrack]] | None = None,
        delay: float = 0.0,
    ) -> None:
        self._similar = similar or []
        self._corpus = corpus or []
        self._free = free or {}
        self.delay = delay
        self.similar_calls: list[tuple[str, str | None, float]] = []
        self.corpus_calls: list[tuple[str, str]] = []
        self.free_calls: list[str] = []

    def similar(self, artist, title, *, history: History, n, new_artist_ratio, timeout):
        self.similar_calls.append((artist, title, new_artist_ratio))
        time.sleep(self.delay)
        return self._similar[:n]

    def corpus(self, artist, title, *, k):
        self.corpus_calls.append((artist, title))
        return self._corpus[:k]

    def free(self, artist, *, limit):
        self.free_calls.append(artist)
        return self._free.get(artist, [])[:limit]


def disc(artist: str, title: str, **kw) -> Pick:
    return Pick(artist=artist, title=title, origin="discover", reason="Similar on Deezer", **kw)


def corp(artist: str, title: str) -> Pick:
    return Pick(artist=artist, title=title, origin="corpus", reason="Sounds like it")


def wire(api: TestClient, sources: FakeSources) -> TestClient:
    api.app.dependency_overrides[get_radio_sources] = lambda: sources  # type: ignore[attr-defined]
    api.app.dependency_overrides[get_match_cache] = lambda: None  # type: ignore[attr-defined]
    return api


@pytest.fixture
def radio_api(make_api, fake_nd: FakeNavidrome, db_path: Path) -> TestClient:
    return make_api(fake_nd, db_connect=connect_to(db_path))


# ── exclude parsing ──────────────────────────────────────────────────────────


def test_parse_exclude_keys_and_ids() -> None:
    keys, ids = parse_exclude("s1, Nujabes::Aruarian%20Dance,A%2C%20B::X%3A%3AY,,")
    assert ids == {"s1"}
    assert keys == {track_key("Nujabes", "Aruarian Dance"), track_key("A, B", "X::Y")}


# ── /api/radio ───────────────────────────────────────────────────────────────


def test_radio_seeded_by_song_id_library_first(radio_api: TestClient) -> None:
    sources = FakeSources(
        similar=[disc("Nujabes", "Aruarian Dance"), disc("ProleteR", "Soul Key")],
        corpus=[corp("Bonobo", "Kiara")],
    )
    r = wire(radio_api, sources).get("/api/radio", params={"songId": "s1"})
    assert r.status_code == 200
    body = r.json()
    assert sources.similar_calls[0][:2] == ("ProleteR", "April Showers")
    assert sources.corpus_calls == [("ProleteR", "April Showers")]
    assert body[0]["source"] == "library"
    assert body[0]["playable"]["songId"] == "s3"
    assert body[0]["playable"]["coverUrl"] == "/api/cover/mf-s3?size=300"
    rest = body[1:]
    assert [(t["artist"], t["source"]) for t in rest] == [
        ("Nujabes", "discover"),
        ("Bonobo", "corpus"),
    ]
    assert all("playable" not in t for t in rest)
    assert rest[0]["reason"] == "Similar on Deezer"


def test_radio_excludes_queue_keys_ids_and_seed(radio_api: TestClient) -> None:
    sources = FakeSources(
        similar=[
            disc("ProleteR", "April Showers"),  # the seed itself
            disc("ProleteR", "Soul Key"),  # in the queue by song id
            disc("Nujabes", "Aruarian Dance"),  # in the queue by key
            disc("nujabes", "aruarian dance"),  # duplicate spelling
            disc("Bonobo", "Kiara"),
        ]
    )
    r = wire(radio_api, sources).get(
        "/api/radio",
        params={"songId": "s1", "exclude": "s3,Nujabes::Aruarian%20Dance"},
    )
    assert [t["title"] for t in r.json()] == ["Kiara"]


def test_radio_caps_two_per_artist_and_limit(radio_api: TestClient) -> None:
    sources = FakeSources(
        similar=[disc("Nujabes", f"T{i}") for i in range(5)]
        + [disc("Bonobo", f"B{i}") for i in range(5)]
        + [disc("Nujabes feat. Shing02", "Luv")]
    )
    r = wire(radio_api, sources).get("/api/radio", params={"artist": "ProleteR", "limit": 3})
    body = r.json()
    assert len(body) == 3
    assert [t["artist"] for t in body].count("Nujabes") == 2
    assert sources.corpus_calls == []  # artist-only seed: no corpus lookup


def test_radio_requires_a_seed(radio_api: TestClient) -> None:
    wire(radio_api, FakeSources())
    assert radio_api.get("/api/radio").status_code == 422
    assert radio_api.get("/api/radio", params={"songId": "nope"}).status_code == 404


def test_radio_corpus_failure_degrades(radio_api: TestClient) -> None:
    class Broken(FakeSources):
        def corpus(self, artist, title, *, k):
            raise duckdb.IOException("locked")

    sources = Broken(similar=[disc("Bonobo", "Kiara")])
    r = wire(radio_api, sources).get(
        "/api/radio", params={"artist": "ProleteR", "title": "April Showers"}
    )
    assert r.status_code == 200
    assert [t["title"] for t in r.json()] == ["Kiara"]


def test_radio_slow_similar_returns_partial(radio_api: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(radio, "RADIO_TIMEOUT_S", 0.5)
    sources = FakeSources(
        similar=[disc("Nujabes", "Aruarian Dance")], corpus=[corp("Bonobo", "Kiara")], delay=2.0
    )
    started = time.monotonic()
    r = wire(radio_api, sources).get(
        "/api/radio", params={"artist": "ProleteR", "title": "April Showers"}
    )
    assert time.monotonic() - started < 1.5
    assert [t["title"] for t in r.json()] == ["Kiara"]


def test_radio_navidrome_down_returns_unmatched(make_api, db_path: Path) -> None:
    api = make_api(refused, db_connect=connect_to(db_path))
    sources = FakeSources(similar=[disc("ProleteR", "Soul Key")])
    r = wire(api, sources).get("/api/radio", params={"artist": "ProleteR"})
    assert r.json() == [
        {
            "artist": "ProleteR",
            "title": "Soul Key",
            "source": "discover",
            "reason": "Similar on Deezer",
        }
    ]


# ── run_parallel ─────────────────────────────────────────────────────────────


def test_run_parallel_keeps_order_drops_failures_and_stragglers() -> None:
    def boom() -> int:
        raise SourceError("down")

    def slow() -> int:
        time.sleep(1.0)
        return 3

    out = run_parallel(
        [("b", lambda: 2), ("x", boom), ("slow", slow), ("a", lambda: 1)], timeout=0.2
    )
    assert out == [("b", 2), ("a", 1)]


# ── /api/discover ────────────────────────────────────────────────────────────


def _play(conn: duckdb.DuckDBPyConnection, artist: str, title: str, nid: str | None, ms: int):
    conn.execute(
        "INSERT INTO plays (ts, track_key, track_name, artist_name, ms_played, navidrome_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            datetime(2026, 10, 30, 12, len(title) % 60),
            track_key(artist, title),
            title,
            artist,
            ms,
            nid,
        ],
    )


def _free(artist: str, title: str) -> FreeTrack:
    return FreeTrack(
        source="archive_org",
        source_id=f"{artist}-{title}",
        artist=artist,
        title=title,
        download_url=f"https://archive.test/{title}.mp3",
        page_url=f"https://archive.test/details/{title}",
        license_url="https://creativecommons.org/licenses/by/4.0/",
    )


def test_discover_sections(radio_api: TestClient, db_path: Path) -> None:
    with duckdb.connect(str(db_path)) as conn:
        _play(conn, "ProleteR", "April Showers", "s1", 200_000)
        _play(conn, "ProleteR", "Soul Key", None, 5_000)  # a skip — not a real play
    sources = FakeSources(
        similar=[
            disc("Nujabes", "Aruarian Dance"),
            disc("ProleteR", "Fallen Angel", known_artist=True),  # not new
            disc("Bonobo", "Kiara", n_plays=1),  # played already
            disc("proleter", "Echo"),  # the seed artist itself, unflagged
        ],
        free={"Nujabes": [_free("Nujabes", "Free One")]},
    )
    r = wire(radio_api, sources).get("/api/discover")
    assert r.status_code == 200
    sections = {s["id"]: s for s in r.json()["sections"]}
    assert [s["title"] for s in r.json()["sections"]] == [
        "In your library, not played yet",
        "New to you",
        "Free to download",
    ]
    unplayed = sections["unplayed"]["tracks"]
    assert {t["playable"]["songId"] for t in unplayed} == {"s2", "s3"}
    assert all(t["source"] == "library" for t in unplayed)

    assert sources.similar_calls[0] == ("ProleteR", None, 1.0)  # seeded from recent plays
    assert [t["title"] for t in sections["new"]["tracks"]] == ["Aruarian Dance"]

    free = sections["free"]["tracks"]
    assert sources.free_calls == ["Nujabes"]
    assert free[0]["free"] == {
        "source": "archive_org",
        "downloadUrl": "https://archive.test/Free One.mp3",
        "pageUrl": "https://archive.test/details/Free One",
        "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
    }
    assert free[0]["reason"] == "Free on Internet Archive"


def test_discover_seeds_from_starred_then_archive(
    radio_api: TestClient, fake_nd: FakeNavidrome, db_path: Path
) -> None:
    sources = FakeSources()
    wire(radio_api, sources)
    fake_nd.starred = ["s3"]
    radio_api.get("/api/discover")
    assert [c[0] for c in sources.similar_calls] == ["ProleteR"]

    fake_nd.starred = []
    with duckdb.connect(str(db_path)) as conn:
        conn.execute("INSERT INTO artists (artist_id, artist_name) VALUES ('a1','Nujabes')")
        conn.execute("INSERT INTO track_artists VALUES ('t1','a1'), ('t2','a1')")
        conn.execute(
            "INSERT INTO playlist_tracks (playlist_id, track_id) VALUES ('p','t1'),('p','t2')"
        )
    sources.similar_calls.clear()
    radio_api.get("/api/discover", params={"refresh": True})
    assert [c[0] for c in sources.similar_calls] == ["Nujabes"]


def test_discover_is_cached(radio_api: TestClient, fake_nd: FakeNavidrome) -> None:
    sources = FakeSources(similar=[disc("Nujabes", "Aruarian Dance")])
    wire(radio_api, sources)
    fake_nd.starred = ["s1"]
    first = radio_api.get("/api/discover").json()
    calls = len(sources.similar_calls)
    assert radio_api.get("/api/discover").json() == first
    assert len(sources.similar_calls) == calls
    radio_api.get("/api/discover", params={"refresh": True})
    assert len(sources.similar_calls) > calls


def test_discover_with_navidrome_down_still_answers(make_api, db_path: Path) -> None:
    api = make_api(refused, db_connect=connect_to(db_path))
    r = wire(api, FakeSources()).get("/api/discover")
    assert r.status_code == 200
    assert [len(s["tracks"]) for s in r.json()["sections"]] == [0, 0, 0]
