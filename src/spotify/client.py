"""
Spotify HTTP client — wraps httpx with Bearer token injection.
Use SpotifyClient for all API calls; auth is handled transparently.
"""

import time

import httpx

from spotify.auth import SpotifyAuth
from utils.exceptions import SpotifyAuthError, SpotifyClientError
from utils.logging import get_logger

log = get_logger(__name__)

BASE_URL = "https://api.spotify.com/v1"
_MAX_RETRIES = 5


def _request(method: str, url: str, **kwargs) -> httpx.Response:
    """Execute an HTTP request with automatic retry on 429."""
    for attempt in range(_MAX_RETRIES):
        response = getattr(httpx, method)(url, **kwargs)
        if response.status_code == 429:
            wait = int(response.headers.get("Retry-After", 2**attempt))
            if wait > 60:
                raise SpotifyClientError(
                    f"Spotify rate limit: Retry-After={wait}s (>{60}s). "
                    "Wait before retrying or check for runaway requests."
                )
            log.warning(
                "spotify.rate_limit",
                wait_s=wait,
                attempt=attempt + 1,
                max_retries=_MAX_RETRIES,
            )
            time.sleep(wait)
            continue
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                try:
                    detail = exc.response.json().get("error", {}).get("message", "")
                except Exception:
                    detail = exc.response.text
                raise SpotifyAuthError(
                    f"Spotify rejected the token (401: {detail}). "
                    "Token may be revoked — client will retry with a refreshed token."
                ) from exc
            raise SpotifyClientError(str(exc)) from exc
        return response
    raise SpotifyClientError("Exceeded max retries due to rate limiting.")


class SpotifyClient:
    """Thin httpx wrapper that keeps the Bearer token fresh."""

    def __init__(self):
        self.auth = SpotifyAuth()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.auth.get_token()}"}

    def _with_auth_retry(self, fn):
        """Call fn(); on SpotifyAuthError force-refresh the token and retry once."""
        try:
            return fn()
        except SpotifyAuthError:
            log.warning("spotify.auth.token_rejected_retrying")
            try:
                self.auth.force_refresh()
            except SpotifyAuthError as exc:
                raise SpotifyAuthError(
                    "Token rejected and refresh failed. "
                    "Delete .spotify_cache and re-authenticate via `make mcp-server`."
                ) from exc
            return fn()

    def get(self, endpoint: str, **params) -> dict:
        url = f"{BASE_URL}/{endpoint.lstrip('/')}"
        return self._with_auth_retry(
            lambda: _request("get", url, headers=self._headers(), params=params).json()
        )

    def post(
        self, endpoint: str, json: dict | None = None, data: dict | None = None
    ) -> dict:
        url = f"{BASE_URL}/{endpoint.lstrip('/')}"
        return self._with_auth_retry(
            lambda: (lambda r: r.json() if r.content else {})(
                _request("post", url, headers=self._headers(), json=json, data=data)
            )
        )

    def get_paginated(self, endpoint: str, **params) -> list[dict]:
        """Follow Spotify pagination and return all items."""
        results = []
        url = f"{BASE_URL}/{endpoint.lstrip('/')}"
        while url:
            data = self._with_auth_retry(
                lambda u=url, p=params: _request(
                    "get", u, headers=self._headers(), params=p
                ).json()
            )
            results.extend(data.get("items", []))
            url = data.get("next")
            params = {}  # next URL already has params baked in
        return results

    def search(self, q: str, type: str = "track", limit: int = 10) -> dict:
        """Search the Spotify catalogue. Returns the raw API response dict."""
        return self.get("search", q=q, type=type, limit=limit)
