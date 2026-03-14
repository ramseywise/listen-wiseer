"""
Spotify read operations — fetch playlists, tracks, audio/artist features, recently played.
All functions accept a SpotifyClient from spotify.client.
Returns validated Pydantic models from data.schemas.
"""

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
        tracks.append(TrackFeatures(
            id=t["id"],
            uri=t["uri"],
            name=t["name"],
            release_date=t["album"].get("release_date", ""),
            artist_ids=[a["id"] for a in t["artists"]],
            artist_names=[a["name"] for a in t["artists"]],
            playlist_id=playlist_id,
        ))

    log.info("spotify.fetch_playlist_tracks", playlist_id=playlist_id, n_tracks=len(tracks))
    return tracks


def fetch_audio_features(client: SpotifyClient, track_ids: list[str]) -> list[AudioFeatures]:
    """Fetch audio features in batches of 100 (Spotify API limit)."""
    results = []
    for i in range(0, len(track_ids), 100):
        batch = track_ids[i : i + 100]
        response = client.get("audio-features", ids=",".join(batch))
        for feat in response.get("audio_features", []):
            if feat is None:
                continue
            results.append(AudioFeatures(
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
            ))
    log.info("spotify.fetch_audio_features", n_tracks=len(results))
    return results


def fetch_artist_features(client: SpotifyClient, artist_ids: list[str]) -> list[ArtistFeatures]:
    """Fetch artist genres and popularity in batches of 50 (Spotify API limit)."""
    results = []
    unique_ids = list(dict.fromkeys(artist_ids))
    for i in range(0, len(unique_ids), 50):
        batch = unique_ids[i : i + 50]
        response = client.get("artists", ids=",".join(batch))
        for artist in response.get("artists", []):
            if artist is None:
                continue
            results.append(ArtistFeatures(
                id=artist["id"],
                popularity=artist.get("popularity", 0),
                genres=artist.get("genres", []),
            ))
    log.info("spotify.fetch_artist_features", n_artists=len(results))
    return results


def fetch_recently_played(client: SpotifyClient, limit: int = 50) -> list[TrackFeatures]:
    """Fetch the current user's recently played tracks (max 50)."""
    response = client.get("me/player/recently-played", limit=min(limit, 50))
    tracks = []
    for item in response.get("items", []):
        t = item.get("track")
        if not t or not t.get("id"):
            continue
        tracks.append(TrackFeatures(
            id=t["id"],
            uri=t["uri"],
            name=t["name"],
            release_date=t["album"].get("release_date", ""),
            artist_ids=[a["id"] for a in t["artists"]],
            artist_names=[a["name"] for a in t["artists"]],
        ))
    log.info("spotify.fetch_recently_played", n_tracks=len(tracks))
    return tracks
