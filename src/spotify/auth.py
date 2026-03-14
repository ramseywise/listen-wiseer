"""
Spotify OAuth — Authorization Code Flow, no spotipy.
Handles browser redirect, token exchange, refresh, and local cache.
"""

import base64
import json
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from utils.config import settings
from utils.exceptions import SpotifyAuthError

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = [
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-library-read",
    "user-read-recently-played",
    "user-top-read",
]
CACHE_PATH = Path(settings.spotify_cache_path)


class SpotifyAuth:
    """Manages Spotify OAuth tokens — exchange, refresh, and file cache."""

    def __init__(self):
        self.client_id = settings.spotify_client_id
        self.client_secret = settings.spotify_client_secret
        self.redirect_uri = settings.spotify_redirect_uri
        self._token_cache: dict = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_token(self) -> str:
        """Return a valid access token, refreshing or re-authorizing as needed."""
        self._load_cache()

        if self._token_cache.get("access_token"):
            if not self._is_expired():
                return self._token_cache["access_token"]
            if self._token_cache.get("refresh_token"):
                self._refresh()
                return self._token_cache["access_token"]

        # No cache or refresh failed — full browser flow
        code = self._browser_flow()
        self._exchange_code(code)
        return self._token_cache["access_token"]

    def force_refresh(self) -> str:
        """Force a new access token via refresh_token regardless of expiry.

        Raises SpotifyAuthError if no refresh token is cached (need full re-auth).
        """
        self._load_cache()
        if not self._token_cache.get("refresh_token"):
            raise SpotifyAuthError(
                "No refresh token in cache — delete .spotify_cache and run "
                "`make mcp-server` to re-authenticate."
            )
        self._refresh()
        return self._token_cache["access_token"]

    # ------------------------------------------------------------------
    # OAuth flow
    # ------------------------------------------------------------------

    def get_auth_url(self) -> str:
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(SCOPES),
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def _browser_flow(self) -> str:
        """Open browser for user login, block until callback returns the code."""
        code_holder: dict = {}

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                if "code" in params:
                    code_holder["code"] = params["code"][0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Auth complete. You can close this tab.")

            def log_message(self, *args):
                pass  # silence server logs

        port = int(self.redirect_uri.split(":")[-1].split("/")[0])
        server = HTTPServer(("127.0.0.1", port), CallbackHandler)

        thread = threading.Thread(target=server.handle_request)
        thread.start()

        webbrowser.open(self.get_auth_url())
        thread.join(timeout=120)
        server.server_close()

        if "code" not in code_holder:
            raise SpotifyAuthError("No auth code received — did you approve in the browser?")
        return code_holder["code"]

    def _exchange_code(self, code: str) -> None:
        """Exchange authorization code for access + refresh tokens."""
        response = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
            },
            headers={"Authorization": f"Basic {self._basic_auth()}"},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SpotifyAuthError(f"Token exchange failed: {exc}") from exc
        self._store(response.json())

    def _refresh(self) -> None:
        """Use refresh token to get a new access token."""
        response = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._token_cache["refresh_token"],
            },
            headers={"Authorization": f"Basic {self._basic_auth()}"},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SpotifyAuthError(f"Token refresh failed: {exc}") from exc
        data = response.json()
        # refresh_token may or may not be rotated
        if "refresh_token" not in data:
            data["refresh_token"] = self._token_cache["refresh_token"]
        self._store(data)

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _store(self, token_data: dict) -> None:
        self._token_cache = {
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token", ""),
            "expires_at": datetime.now().timestamp() + token_data["expires_in"],
        }
        CACHE_PATH.write_text(json.dumps(self._token_cache))

    def _load_cache(self) -> None:
        if CACHE_PATH.exists():
            self._token_cache = json.loads(CACHE_PATH.read_text())

    def _is_expired(self) -> bool:
        return time.time() > self._token_cache.get("expires_at", 0) - 60

    def _basic_auth(self) -> str:
        return base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
