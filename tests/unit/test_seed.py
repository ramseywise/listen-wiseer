"""Unit tests for library.seed — archive.org picks, downloads, Navidrome admin + scan."""

import httpx
import pytest

from library import seed
from sources.http import SourceClient
from sources.schemas import FreeTrack
from sources.subsonic import SubsonicClient
from utils.exceptions import SourceError


def _source(handler) -> SourceClient:
    return SourceClient("test", "https://api.test/", transport=httpx.MockTransport(handler))


def _item(identifier: str, n_files: int) -> dict:
    return {
        "metadata": {"identifier": identifier, "creator": "Band", "licenseurl": "https://cc/by"},
        "files": [
            {"name": f"{i:02}.mp3", "format": "VBR MP3", "title": f"Song {i}"}
            for i in range(1, n_files + 1)
        ],
    }


class TestSeedTracks:
    def test_takes_first_n_per_item_and_skips_failures(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/broken"):
                return httpx.Response(500)
            return httpx.Response(200, json=_item("good", 4))

        tracks = seed.seed_tracks((("good", 2), ("broken", 3)), client=_source(handler))
        assert [t.title for t in tracks] == ["Song 1", "Song 2"]
        assert {t.source for t in tracks} == {"archive_org"}


class TestDownloadAll:
    def test_failed_download_is_skipped(self, mem_conn, tmp_path):
        good = FreeTrack(source="archive_org", source_id="a/1", artist="Band", title="One",
                         download_url="https://cdn.test/ok")  # fmt: skip
        bad = good.model_copy(update={"title": "Two", "download_url": "https://cdn.test/gone"})

        def cdn(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404 if request.url.path == "/gone" else 200, content=b"mp3")

        paths = seed.download_all(mem_conn, [good, bad], library_dir=tmp_path, client=_source(cdn))
        assert paths == [tmp_path / "Band" / "One.mp3"]


class TestEnsureAdmin:
    @pytest.mark.parametrize("status,created", [(200, True), (403, False)])
    async def test_first_run_vs_existing(self, status, created):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(status, json={})

        transport = httpx.MockTransport(handler)
        assert (
            await seed.ensure_admin("http://nd.test", "admin", "pw", transport=transport) is created
        )
        assert seen[0].url.path == "/auth/createAdmin"
        assert seen[0].method == "POST"

    async def test_server_error_raises(self):
        transport = httpx.MockTransport(lambda _r: httpx.Response(500))
        with pytest.raises(SourceError):
            await seed.ensure_admin("http://nd.test", "admin", "pw", transport=transport)


class TestScanAndWait:
    async def test_polls_until_scan_finishes(self):
        states = iter([True, True, False])
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path.removeprefix("/rest/"))
            scanning = next(states)
            body = {"status": "ok", "scanStatus": {"scanning": scanning, "count": 5}}
            return httpx.Response(200, json={"subsonic-response": body})

        client = SubsonicClient("http://nd.test", "u", "p", transport=httpx.MockTransport(handler))
        status = await seed.scan_and_wait(client, poll_s=0)
        assert calls == ["startScan", "getScanStatus", "getScanStatus"]
        assert (status.scanning, status.count) == (False, 5)
