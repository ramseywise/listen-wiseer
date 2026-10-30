"""Unit tests for library.migrate_playlists — local_playlists → fake Navidrome."""

import asyncio

import duckdb
import httpx

from etl.db import init_schema
from library.migrate_playlists import load_local, migrate, render
from library.playlists import save_playlist
from sources.schemas import TrackRef
from sources.subsonic import SubsonicClient
from tests.unit.api.conftest import FakeNavidrome


def _client(fake: FakeNavidrome) -> SubsonicClient:
    return SubsonicClient("http://nd.test", "me", "pw", transport=httpx.MockTransport(fake))


def _run(fake: FakeNavidrome, local, **kw):
    async def go():
        client = _client(fake)
        try:
            return await migrate(client, local, **kw)
        finally:
            await client.aclose()

    return asyncio.run(go())


def test_no_rows_is_noop_without_network() -> None:
    def explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    async def go():
        client = SubsonicClient("http://nd.test", "u", "p", transport=httpx.MockTransport(explode))
        try:
            return await migrate(client, [])
        finally:
            await client.aclose()

    assert asyncio.run(go()) == []
    assert render([], dry_run=False) == "No local playlists to migrate.\n"


def test_migrates_with_unmatched_report(tmp_path) -> None:
    conn = duckdb.connect(str(tmp_path / "m.db"))
    init_schema(conn)
    save_playlist(
        conn,
        "Rainy",
        [
            TrackRef(artist="ProleteR", title="Soul Key"),
            TrackRef(artist="Nobody", title="Nothing Here"),
        ],
    )
    local = load_local(conn)
    conn.close()

    fake = FakeNavidrome()
    results = _run(fake, local)
    assert [p["name"] for p in fake.playlists.values()] == ["Rainy"]
    assert next(iter(fake.playlists.values()))["ids"] == ["s3"]
    assert results[0].navidrome_id and [t.title for t in results[0].unmatched] == ["Nothing Here"]
    out = render(results, dry_run=False)
    assert "+ Rainy: created with 1/2 tracks" in out and "Nobody — Nothing Here" in out

    again = _run(fake, local)  # same name exists now → skipped, not duplicated
    assert again[0].skipped and len(fake.playlists) == 1


def test_dry_run_creates_nothing() -> None:
    fake = FakeNavidrome()
    results = _run(
        fake, [("X", [TrackRef(artist="ProleteR", title="April Showers")])], dry_run=True
    )
    assert fake.playlists == {} and results[0].navidrome_id is None
    assert "would create with 1/1" in render(results, dry_run=True)
