"""
Spotify read operations — fetch playlists, tracks, audio/artist features, recently played.
All functions accept a SpotifyClient from spotify.client.
Returns validated Pydantic models from data.schemas.
"""

import time

from spotify.client import SpotifyClient
from utils.logging import get_logger
from utils.schemas import ArtistFeatures, AudioFeatures, TrackFeatures

log = get_logger(__name__)


def fetch_my_playlists(client: SpotifyClient) -> list[dict]:
    """Return all playlists owned or followed by the current user."""
    results = client.get_paginated("me/playlists", limit=50)
    log.info("spotify.fetch_my_playlists", n_playlists=len(results))
    return results


def fetch_playlist_tracks(client: SpotifyClient, playlist_id: str) -> list[TrackFeatures]:
    """Fetch all tracks from a playlist, handling pagination."""
    items = client.get_paginated(f"playlists/{playlist_id}/tracks", limit=100)

    tracks = []
    for item in items:
        t = item.get("track")
        if not t or not t.get("id"):
            continue
        tracks.append(
            TrackFeatures(
                id=t["id"],
                uri=t["uri"],
                name=t["name"],
                release_date=t["album"].get("release_date", ""),
                artist_ids=[a["id"] for a in t["artists"]],
                artist_names=[a["name"] for a in t["artists"]],
                playlist_id=playlist_id,
            )
        )

    log.info("spotify.fetch_playlist_tracks", playlist_id=playlist_id, n_tracks=len(tracks))
    return tracks


def fetch_audio_features(client: SpotifyClient, track_ids: list[str]) -> list[AudioFeatures]:
    """Fetch audio features in batches of 100 (Spotify API limit)."""
    results = []
    for i in range(0, len(track_ids), 100):
        batch = track_ids[i : i + 100]
        response = client.get("audio-features", ids=",".join(batch))
        time.sleep(0.1)
        for feat in response.get("audio_features", []):
            if feat is None:
                continue
            results.append(
                AudioFeatures(
                    id=feat["id"],
                    danceability=feat.get("danceability", 0.0),
                    energy=feat.get("energy", 0.0),
                    loudness=feat.get("loudness", 0.0),
                    speechiness=feat.get("speechiness", 0.0),
                    acousticness=feat.get("acousticness", 0.0),
                    instrumentalness=feat.get("instrumentalness", 0.0),
                    liveness=feat.get("liveness", 0.0),
                    valence=feat.get("valence", 0.0),
                    tempo=feat.get("tempo", 0.0),
                    key=feat.get("key", 0),
                    mode=feat.get("mode", 0),
                    duration_ms=feat.get("duration_ms", 0),
                    time_signature=feat.get("time_signature", 4),
                )
            )
    log.info("spotify.fetch_audio_features", n_tracks=len(results))
    return results


def fetch_artist_features(client: SpotifyClient, artist_ids: list[str]) -> list[ArtistFeatures]:
    """Fetch artist genres and popularity in batches of 50 (Spotify API limit)."""
    results = []
    unique_ids = list(dict.fromkeys(artist_ids))
    for i in range(0, len(unique_ids), 50):
        batch = unique_ids[i : i + 50]
        response = client.get("artists", ids=",".join(batch))
        time.sleep(0.1)
        for artist in response.get("artists", []):
            if artist is None:
                continue
            results.append(
                ArtistFeatures(
                    id=artist["id"],
                    popularity=artist.get("popularity", 0),
                    genres=artist.get("genres", []),
                )
            )
    log.info("spotify.fetch_artist_features", n_artists=len(results))
    return results


def fetch_related_artists(client: SpotifyClient, artist_id: str) -> list[dict]:
    """Fetch up to 20 related artists for a given artist ID."""
    response = client.get(f"artists/{artist_id}/related-artists")
    artists = response.get("artists", [])
    log.info("spotify.fetch_related_artists", artist_id=artist_id, n=len(artists))
    return [{"id": a["id"], "name": a["name"], "genres": a.get("genres", [])[:3]} for a in artists]


def fetch_top_tracks(
    client: SpotifyClient,
    time_range: str = "medium_term",
    limit: int = 20,
) -> list[TrackFeatures]:
    """Fetch user's top tracks. time_range: short_term, medium_term, long_term."""
    response = client.get("me/top/tracks", time_range=time_range, limit=limit)
    tracks = []
    for t in response.get("items", []):
        if not t.get("id"):
            continue
        tracks.append(
            TrackFeatures(
                id=t["id"],
                uri=t["uri"],
                name=t["name"],
                release_date=t["album"].get("release_date", ""),
                artist_ids=[a["id"] for a in t["artists"]],
                artist_names=[a["name"] for a in t["artists"]],
            )
        )
    log.info("spotify.fetch_top_tracks", time_range=time_range, n_tracks=len(tracks))
    return tracks


def fetch_top_artists(
    client: SpotifyClient,
    time_range: str = "medium_term",
    limit: int = 20,
) -> list[dict]:
    """Fetch user's top artists. time_range: short_term, medium_term, long_term."""
    response = client.get("me/top/artists", time_range=time_range, limit=limit)
    artists = response.get("items", [])
    log.info("spotify.fetch_top_artists", time_range=time_range, n_artists=len(artists))
    return [
        {
            "id": a["id"],
            "name": a["name"],
            "genres": a.get("genres", [])[:5],
            "popularity": a.get("popularity", 0),
        }
        for a in artists
    ]


def fetch_artist_info(client: SpotifyClient, artist_id: str) -> dict:
    """Fetch artist metadata: name, genres, popularity, followers."""
    response = client.get(f"artists/{artist_id}")
    log.info("spotify.fetch_artist_info", artist_id=artist_id)
    return {
        "id": response.get("id", ""),
        "name": response.get("name", ""),
        "genres": response.get("genres", []),
        "popularity": response.get("popularity", 0),
        "followers": response.get("followers", {}).get("total", 0),
    }


def fetch_artist_top_tracks(client: SpotifyClient, artist_id: str) -> list[TrackFeatures]:
    """Fetch artist's top 10 tracks (market=US)."""
    response = client.get(f"artists/{artist_id}/top-tracks", market="US")
    tracks = []
    for t in response.get("tracks", []):
        if not t.get("id"):
            continue
        tracks.append(
            TrackFeatures(
                id=t["id"],
                uri=t["uri"],
                name=t["name"],
                release_date=t["album"].get("release_date", ""),
                artist_ids=[a["id"] for a in t["artists"]],
                artist_names=[a["name"] for a in t["artists"]],
            )
        )
    log.info("spotify.fetch_artist_top_tracks", artist_id=artist_id, n_tracks=len(tracks))
    return tracks


def fetch_artist_albums(client: SpotifyClient, artist_id: str) -> list[dict]:
    """Fetch artist's albums and singles (up to 20)."""
    response = client.get(
        f"artists/{artist_id}/albums",
        include_groups="album,single",
        limit=20,
    )
    albums = response.get("items", [])
    log.info("spotify.fetch_artist_albums", artist_id=artist_id, n_albums=len(albums))
    return [
        {
            "id": a["id"],
            "name": a["name"],
            "release_date": a.get("release_date", ""),
            "total_tracks": a.get("total_tracks", 0),
            "type": a.get("album_type", ""),
        }
        for a in albums
    ]


def fetch_spotify_recommendations(
    client: SpotifyClient,
    seed_tracks: list[str] | None = None,
    seed_artists: list[str] | None = None,
    seed_genres: list[str] | None = None,
    limit: int = 20,
) -> list[TrackFeatures]:
    """Get Spotify's native recommendations from seed tracks, artists, or genres.

    Total seeds across all three lists must be 1–5.
    """
    params: dict = {"limit": limit}
    if seed_tracks:
        params["seed_tracks"] = ",".join(seed_tracks[:5])
    if seed_artists:
        params["seed_artists"] = ",".join(seed_artists[:5])
    if seed_genres:
        params["seed_genres"] = ",".join(seed_genres[:5])

    response = client.get("recommendations", **params)
    tracks = []
    for t in response.get("tracks", []):
        if not t.get("id"):
            continue
        tracks.append(
            TrackFeatures(
                id=t["id"],
                uri=t["uri"],
                name=t["name"],
                release_date=t["album"].get("release_date", ""),
                artist_ids=[a["id"] for a in t["artists"]],
                artist_names=[a["name"] for a in t["artists"]],
            )
        )
    log.info("spotify.fetch_spotify_recommendations", n_tracks=len(tracks))
    return tracks


def fetch_recently_played(client: SpotifyClient, limit: int = 50) -> list[TrackFeatures]:
    """Fetch the current user's recently played tracks (max 50)."""
    response = client.get("me/player/recently-played", limit=min(limit, 50))
    tracks = []
    for item in response.get("items", []):
        t = item.get("track")
        if not t or not t.get("id"):
            continue
        tracks.append(
            TrackFeatures(
                id=t["id"],
                uri=t["uri"],
                name=t["name"],
                release_date=t["album"].get("release_date", ""),
                artist_ids=[a["id"] for a in t["artists"]],
                artist_names=[a["name"] for a in t["artists"]],
            )
        )
    log.info("spotify.fetch_recently_played", n_tracks=len(tracks))
    return tracks
