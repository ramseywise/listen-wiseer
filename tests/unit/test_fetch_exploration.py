"""Unit tests for Phase 7a exploration fetch functions.

All tests use synthetic fixtures — no network calls, no real Spotify credentials.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from spotify.fetch import (
    fetch_artist_albums,
    fetch_artist_info,
    fetch_artist_top_tracks,
    fetch_spotify_recommendations,
    fetch_top_artists,
    fetch_top_tracks,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_track(id: str = "t1", name: str = "Track One", artist: str = "Artist A") -> dict:
    return {
        "id": id,
        "uri": f"spotify:track:{id}",
        "name": name,
        "album": {"release_date": "2020-01-01"},
        "artists": [{"id": "a1", "name": artist}],
    }


def _make_artist(id: str = "a1", name: str = "Artist A", genres: list[str] | None = None) -> dict:
    return {
        "id": id,
        "name": name,
        "genres": genres or ["jazz", "soul"],
        "popularity": 72,
        "followers": {"total": 500_000},
    }


@pytest.fixture()
def client() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# fetch_top_tracks
# ---------------------------------------------------------------------------


class TestFetchTopTracks:
    def test_returns_track_features(self, client: MagicMock) -> None:
        client.get.return_value = {"items": [_make_track("t1", "Song A", "Band B")]}
        tracks = fetch_top_tracks(client, time_range="short_term")
        assert len(tracks) == 1
        assert tracks[0].id == "t1"
        assert tracks[0].name == "Song A"
        assert "Band B" in tracks[0].artist_names

    def test_passes_time_range_to_client(self, client: MagicMock) -> None:
        client.get.return_value = {"items": []}
        fetch_top_tracks(client, time_range="long_term", limit=10)
        client.get.assert_called_once_with("me/top/tracks", time_range="long_term", limit=10)

    def test_empty_items_returns_empty_list(self, client: MagicMock) -> None:
        client.get.return_value = {"items": []}
        assert fetch_top_tracks(client) == []

    def test_skips_tracks_without_id(self, client: MagicMock) -> None:
        bad = _make_track()
        bad["id"] = ""
        client.get.return_value = {"items": [bad, _make_track("t2", "Good Track")]}
        tracks = fetch_top_tracks(client)
        assert len(tracks) == 1
        assert tracks[0].id == "t2"


# ---------------------------------------------------------------------------
# fetch_top_artists
# ---------------------------------------------------------------------------


class TestFetchTopArtists:
    def test_returns_artist_dicts(self, client: MagicMock) -> None:
        client.get.return_value = {"items": [_make_artist("a1", "Miles Davis", ["jazz"])]}
        artists = fetch_top_artists(client, time_range="medium_term")
        assert len(artists) == 1
        assert artists[0]["name"] == "Miles Davis"
        assert "jazz" in artists[0]["genres"]
        assert artists[0]["popularity"] == 72

    def test_passes_time_range_to_client(self, client: MagicMock) -> None:
        client.get.return_value = {"items": []}
        fetch_top_artists(client, time_range="long_term", limit=5)
        client.get.assert_called_once_with("me/top/artists", time_range="long_term", limit=5)

    def test_genres_capped_at_five(self, client: MagicMock) -> None:
        many_genres = ["g1", "g2", "g3", "g4", "g5", "g6", "g7"]
        artist = _make_artist("a1", "Prolific", many_genres)
        client.get.return_value = {"items": [artist]}
        result = fetch_top_artists(client)
        assert len(result[0]["genres"]) == 5


# ---------------------------------------------------------------------------
# fetch_artist_info
# ---------------------------------------------------------------------------


class TestFetchArtistInfo:
    def test_returns_expected_fields(self, client: MagicMock) -> None:
        client.get.return_value = _make_artist("a42", "Floating Points", ["electronic", "jazz"])
        info = fetch_artist_info(client, "a42")
        assert info["id"] == "a42"
        assert info["name"] == "Floating Points"
        assert "electronic" in info["genres"]
        assert info["popularity"] == 72
        assert info["followers"] == 500_000

    def test_calls_correct_endpoint(self, client: MagicMock) -> None:
        client.get.return_value = _make_artist()
        fetch_artist_info(client, "xyz")
        client.get.assert_called_once_with("artists/xyz")

    def test_missing_followers_defaults_to_zero(self, client: MagicMock) -> None:
        data = _make_artist()
        data.pop("followers")
        client.get.return_value = data
        info = fetch_artist_info(client, "a1")
        assert info["followers"] == 0


# ---------------------------------------------------------------------------
# fetch_artist_top_tracks
# ---------------------------------------------------------------------------


class TestFetchArtistTopTracks:
    def test_returns_track_features(self, client: MagicMock) -> None:
        client.get.return_value = {"tracks": [_make_track("t1", "Top Track")]}
        tracks = fetch_artist_top_tracks(client, "a1")
        assert len(tracks) == 1
        assert tracks[0].name == "Top Track"

    def test_calls_correct_endpoint_with_market(self, client: MagicMock) -> None:
        client.get.return_value = {"tracks": []}
        fetch_artist_top_tracks(client, "a99")
        client.get.assert_called_once_with("artists/a99/top-tracks", market="US")

    def test_skips_tracks_without_id(self, client: MagicMock) -> None:
        bad = _make_track()
        bad["id"] = ""
        client.get.return_value = {"tracks": [bad, _make_track("t2", "Valid")]}
        tracks = fetch_artist_top_tracks(client, "a1")
        assert len(tracks) == 1
        assert tracks[0].id == "t2"


# ---------------------------------------------------------------------------
# fetch_artist_albums
# ---------------------------------------------------------------------------


class TestFetchArtistAlbums:
    def test_returns_album_dicts(self, client: MagicMock) -> None:
        client.get.return_value = {
            "items": [
                {
                    "id": "alb1",
                    "name": "Blue",
                    "release_date": "1971-06-22",
                    "total_tracks": 10,
                    "album_type": "album",
                }
            ]
        }
        albums = fetch_artist_albums(client, "a1")
        assert len(albums) == 1
        assert albums[0]["name"] == "Blue"
        assert albums[0]["type"] == "album"

    def test_calls_correct_endpoint(self, client: MagicMock) -> None:
        client.get.return_value = {"items": []}
        fetch_artist_albums(client, "a77")
        client.get.assert_called_once_with(
            "artists/a77/albums",
            include_groups="album,single",
            limit=20,
        )

    def test_empty_discography_returns_empty_list(self, client: MagicMock) -> None:
        client.get.return_value = {"items": []}
        assert fetch_artist_albums(client, "a1") == []


# ---------------------------------------------------------------------------
# fetch_spotify_recommendations
# ---------------------------------------------------------------------------


class TestFetchSpotifyRecommendations:
    def test_returns_track_features(self, client: MagicMock) -> None:
        client.get.return_value = {"tracks": [_make_track("t1", "Rec Track")]}
        tracks = fetch_spotify_recommendations(client, seed_tracks=["t_seed"])
        assert len(tracks) == 1
        assert tracks[0].name == "Rec Track"

    def test_seed_tracks_joined_as_csv(self, client: MagicMock) -> None:
        client.get.return_value = {"tracks": []}
        fetch_spotify_recommendations(client, seed_tracks=["a", "b", "c"])
        call_kwargs = client.get.call_args[1]
        assert call_kwargs["seed_tracks"] == "a,b,c"

    def test_seed_artists_joined_as_csv(self, client: MagicMock) -> None:
        client.get.return_value = {"tracks": []}
        fetch_spotify_recommendations(client, seed_artists=["x", "y"])
        call_kwargs = client.get.call_args[1]
        assert call_kwargs["seed_artists"] == "x,y"

    def test_seeds_capped_at_five(self, client: MagicMock) -> None:
        client.get.return_value = {"tracks": []}
        fetch_spotify_recommendations(client, seed_tracks=["a", "b", "c", "d", "e", "f"])
        call_kwargs = client.get.call_args[1]
        assert len(call_kwargs["seed_tracks"].split(",")) == 5

    def test_omits_empty_seed_params(self, client: MagicMock) -> None:
        client.get.return_value = {"tracks": []}
        fetch_spotify_recommendations(client, seed_genres=["jazz"])
        call_kwargs = client.get.call_args[1]
        assert "seed_tracks" not in call_kwargs
        assert "seed_artists" not in call_kwargs
        assert call_kwargs["seed_genres"] == "jazz"

    def test_empty_tracks_returns_empty_list(self, client: MagicMock) -> None:
        client.get.return_value = {"tracks": []}
        assert fetch_spotify_recommendations(client, seed_genres=["pop"]) == []
