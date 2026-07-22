"""Unit tests for SpotifyClient — mock httpx, assert typed exceptions."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from spotify.client import SpotifyClient
from utils.exceptions import SpotifyClientError


def _make_response(status_code: int, json_body: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.content = b"body" if json_body is not None else b""
    response.json.return_value = json_body or {}

    if status_code >= 400:
        http_error = httpx.HTTPStatusError(
            f"{status_code} Error",
            request=MagicMock(),
            response=response,
        )
        response.raise_for_status.side_effect = http_error
    else:
        response.raise_for_status.return_value = None

    return response


@pytest.fixture()
def client() -> SpotifyClient:
    """SpotifyClient with a stubbed auth layer."""
    with patch("spotify.client.SpotifyAuth") as mock_auth_cls:
        mock_auth_cls.return_value.get_token.return_value = "fake-token"
        yield SpotifyClient()


class TestSpotifyClientGet:
    def test_returns_dict_on_200(self, client: SpotifyClient) -> None:
        payload = {"id": "abc", "name": "Test Track"}
        with patch("httpx.get", return_value=_make_response(200, payload)):
            result = client.get("tracks/abc")
        assert result == payload

    def test_raises_spotify_client_error_on_401(self, client: SpotifyClient) -> None:
        with patch("httpx.get", return_value=_make_response(401)):
            with pytest.raises(SpotifyClientError):
                client.get("tracks/abc")

    def test_raises_spotify_client_error_on_404(self, client: SpotifyClient) -> None:
        with patch("httpx.get", return_value=_make_response(404)):
            with pytest.raises(SpotifyClientError):
                client.get("tracks/missing")

    def test_raises_spotify_client_error_on_500(self, client: SpotifyClient) -> None:
        with patch("httpx.get", return_value=_make_response(500)):
            with pytest.raises(SpotifyClientError):
                client.get("tracks/abc")

    def test_spotify_client_error_is_chained(self, client: SpotifyClient) -> None:
        with patch("httpx.get", return_value=_make_response(401)):
            with pytest.raises(SpotifyClientError) as exc_info:
                client.get("tracks/abc")
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)


class TestSpotifyClientPost:
    def test_returns_dict_on_200(self, client: SpotifyClient) -> None:
        payload = {"snapshot_id": "xyz"}
        with patch("httpx.post", return_value=_make_response(200, payload)):
            result = client.post("playlists/1/tracks", json={"uris": []})
        assert result == payload

    def test_raises_spotify_client_error_on_403(self, client: SpotifyClient) -> None:
        with patch("httpx.post", return_value=_make_response(403)):
            with pytest.raises(SpotifyClientError):
                client.post("playlists/1/tracks", json={"uris": []})


class TestSpotifyClientSearch:
    def test_search_calls_get_with_correct_params(self, client: SpotifyClient) -> None:
        payload = {"tracks": {"items": []}}
        with patch.object(client, "get", return_value=payload) as mock_get:
            result = client.search(q="Radiohead", type="track", limit=5)
        mock_get.assert_called_once_with("search", q="Radiohead", type="track", limit=5)
        assert result == payload

    def test_search_default_params(self, client: SpotifyClient) -> None:
        payload = {"tracks": {"items": []}}
        with patch.object(client, "get", return_value=payload) as mock_get:
            client.search(q="jazz")
        mock_get.assert_called_once_with("search", q="jazz", type="track", limit=10)


class TestSpotifyClientGetPaginated:
    def test_returns_all_items_across_pages(self, client: SpotifyClient) -> None:
        page1 = _make_response(
            200, {"items": [{"id": "1"}], "next": "https://api.spotify.com/v1/page2"}
        )
        page2 = _make_response(200, {"items": [{"id": "2"}], "next": None})
        with patch("httpx.get", side_effect=[page1, page2]):
            results = client.get_paginated("playlists/1/tracks")
        assert results == [{"id": "1"}, {"id": "2"}]

    def test_raises_spotify_client_error_on_401(self, client: SpotifyClient) -> None:
        with patch("httpx.get", return_value=_make_response(401)):
            with pytest.raises(SpotifyClientError):
                client.get_paginated("playlists/1/tracks")


class TestFetchRelatedArtists:
    def test_happy_path(self, client: SpotifyClient) -> None:
        from spotify.fetch import fetch_related_artists

        payload = {
            "artists": [
                {"id": "a1", "name": "Artist One", "genres": ["rock", "indie", "alt", "extra"]},
                {"id": "a2", "name": "Artist Two", "genres": ["jazz"]},
            ]
        }
        with patch.object(client, "get", return_value=payload):
            result = fetch_related_artists(client, "seed123")

        assert len(result) == 2
        assert result[0]["name"] == "Artist One"
        assert result[1]["name"] == "Artist Two"

    def test_empty_response(self, client: SpotifyClient) -> None:
        from spotify.fetch import fetch_related_artists

        with patch.object(client, "get", return_value={"artists": []}):
            result = fetch_related_artists(client, "seed123")

        assert result == []

    def test_truncates_genres_to_three(self, client: SpotifyClient) -> None:
        from spotify.fetch import fetch_related_artists

        payload = {
            "artists": [
                {"id": "a1", "name": "A", "genres": ["g1", "g2", "g3", "g4", "g5"]},
            ]
        }
        with patch.object(client, "get", return_value=payload):
            result = fetch_related_artists(client, "seed123")

        assert len(result[0]["genres"]) == 3
