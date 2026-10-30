"""
Shared HTTP client for free music-data sources.
Adds a User-Agent, a per-client minimum request interval, and retry on 429/503.

Contract for callers: "not found" (404 / 204) returns ``{}``; any other failure
raises ``SourceError``.
"""

import threading
import time
from pathlib import Path

import httpx

from utils.config import settings
from utils.exceptions import SourceError
from utils.logging import get_logger

log = get_logger(__name__)

_MAX_RETRIES = 4
_MAX_WAIT_S = 30.0


def _retry_after(response: httpx.Response, attempt: int) -> float:
    try:
        wait = float(response.headers.get("Retry-After", 2**attempt))
    except ValueError:
        wait = float(2**attempt)
    return min(wait, _MAX_WAIT_S)


class SourceClient:
    """Rate-limited JSON GET client for one upstream API."""

    def __init__(
        self,
        name: str,
        base_url: str,
        *,
        min_interval: float = 0.0,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ):
        self.name = name
        self._min_interval = min_interval
        self._last_request = 0.0
        self._throttle_lock = threading.Lock()  # the API calls one client from worker threads
        self._default_params = params or {}
        self._http = httpx.Client(
            base_url=base_url,
            headers={"User-Agent": settings.source_user_agent, **(headers or {})},
            timeout=timeout,
            transport=transport,
        )

    def _throttle(self) -> None:
        with self._throttle_lock:
            wait = self._min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def get_json(self, path: str, **params) -> dict:
        for attempt in range(_MAX_RETRIES):
            self._throttle()
            try:
                response = self._http.get(path, params={**self._default_params, **params})
            except httpx.HTTPError as exc:
                raise SourceError(f"{self.name}: request to {path!r} failed: {exc}") from exc

            if response.status_code in (429, 503):
                wait = _retry_after(response, attempt)
                log.warning(
                    "source.rate_limited", source=self.name, wait_s=wait, attempt=attempt + 1
                )
                time.sleep(wait)
                continue
            if response.status_code == 404:
                return {}
            if response.is_error:
                raise SourceError(f"{self.name}: HTTP {response.status_code} on {path!r}")
            return response.json() if response.content else {}
        raise SourceError(f"{self.name}: still rate-limited after {_MAX_RETRIES} attempts")

    def download(self, url: str, dest: Path) -> Path:
        """Stream ``url`` to ``dest`` via a ``.part`` file, so a failed download leaves nothing.

        Default params (API keys) are not sent — download hosts are often third-party CDNs.
        """
        self._throttle()
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        try:
            with self._http.stream("GET", url, follow_redirects=True) as response:
                if response.is_error:
                    raise SourceError(f"{self.name}: HTTP {response.status_code} on {url!r}")
                with part.open("wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
        except httpx.HTTPError as exc:
            part.unlink(missing_ok=True)
            raise SourceError(f"{self.name}: download of {url!r} failed: {exc}") from exc
        except SourceError:
            part.unlink(missing_ok=True)
            raise
        return part.replace(dest)
