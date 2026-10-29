"""Fixtures for sources/ tests — SourceClient over httpx.MockTransport, no network."""

from collections.abc import Callable

import httpx
import pytest

from sources.http import SourceClient

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def make_client() -> Callable[..., SourceClient]:
    def _make(handler: Handler, **kwargs) -> SourceClient:
        return SourceClient(
            "test", "https://api.test/", transport=httpx.MockTransport(handler), **kwargs
        )

    return _make


@pytest.fixture
def json_client(make_client) -> Callable[[dict], tuple[SourceClient, list[httpx.Request]]]:
    """Client that always answers with ``payload``; also returns the captured requests."""

    def _make(payload: dict) -> tuple[SourceClient, list[httpx.Request]]:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=payload)

        return make_client(handler), seen

    return _make


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("sources.http.time.sleep", lambda _s: None)
