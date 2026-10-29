"""Unit tests for sources.http.SourceClient."""

import httpx
import pytest

from utils.exceptions import SourceError


class TestGetJson:
    def test_returns_json_and_merges_default_params(self, make_client):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"ok": True})

        client = make_client(handler, params={"fmt": "json"})
        assert client.get_json("thing", q="x") == {"ok": True}
        assert seen[0].url.params["fmt"] == "json"
        assert seen[0].url.params["q"] == "x"

    def test_sends_user_agent(self, make_client):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={})

        make_client(handler).get_json("thing")
        assert seen[0].headers["User-Agent"].startswith("listen-wiseer/")

    @pytest.mark.parametrize("status", [204, 404])
    def test_not_found_returns_empty(self, make_client, status):
        client = make_client(lambda _r: httpx.Response(status))
        assert client.get_json("thing") == {}

    def test_retries_on_429_then_succeeds(self, make_client):
        responses = iter(
            [
                httpx.Response(429, headers={"Retry-After": "1"}),
                httpx.Response(503),
                httpx.Response(200, json={"ok": 1}),
            ]
        )
        client = make_client(lambda _r: next(responses))
        assert client.get_json("thing") == {"ok": 1}

    def test_gives_up_after_max_retries(self, make_client):
        client = make_client(lambda _r: httpx.Response(429, headers={"Retry-After": "soon"}))
        with pytest.raises(SourceError, match="rate-limited"):
            client.get_json("thing")

    def test_http_error_raises_source_error(self, make_client):
        client = make_client(lambda _r: httpx.Response(500))
        with pytest.raises(SourceError, match="HTTP 500"):
            client.get_json("thing")

    def test_transport_error_raises_source_error(self, make_client):
        def handler(request):
            raise httpx.ConnectError("boom", request=request)

        with pytest.raises(SourceError, match="failed"):
            make_client(handler).get_json("thing")


class TestDownload:
    def test_streams_to_dest_without_default_params(self, make_client, tmp_path):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, content=b"ID3audio")

        client = make_client(handler, params={"client_id": "secret"})
        dest = client.download("https://cdn.test/a.mp3", tmp_path / "x" / "a.mp3")
        assert dest.read_bytes() == b"ID3audio"
        assert "client_id" not in str(seen[0].url)

    def test_http_error_leaves_no_file(self, make_client, tmp_path):
        client = make_client(lambda _r: httpx.Response(403))
        with pytest.raises(SourceError, match="HTTP 403"):
            client.download("https://cdn.test/a.mp3", tmp_path / "a.mp3")
        assert list(tmp_path.iterdir()) == []

    def test_transport_error_leaves_no_file(self, make_client, tmp_path):
        def handler(request):
            raise httpx.ReadError("cut", request=request)

        with pytest.raises(SourceError, match="download"):
            make_client(handler).download("https://cdn.test/a.mp3", tmp_path / "a.mp3")
        assert list(tmp_path.iterdir()) == []
