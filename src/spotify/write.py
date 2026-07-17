"""
Spotify write operations — create playlists, add tracks.
"""

from spotify.client import SpotifyClient
from utils.config import settings


class SpotifyActions:
    """Write operations against the Spotify API."""

    def __init__(self, client: SpotifyClient):
        self.client = client
        self.user_id = settings.spotify_user_id

    def create_playlist(self, name: str, description: str = "") -> str:
        """Create a private playlist and return its ID."""
        result = self.client.post(
            f"users/{self.user_id}/playlists",
            json={"name": name, "public": False, "description": description},
        )
        return result["id"]

    def add_tracks(self, playlist_id: str, track_ids: list[str]) -> None:
        """Add tracks in batches of 100 (Spotify API limit)."""
        uris = [f"spotify:track:{t}" if not t.startswith("spotify:") else t for t in track_ids]
        for i in range(0, len(uris), 100):
            self.client.post(
                f"playlists/{playlist_id}/tracks",
                json={"uris": uris[i : i + 100]},
            )

    def create_playlist_with_tracks(
        self, name: str, track_ids: list[str], description: str = ""
    ) -> str:
        """Create a playlist, populate it, and return the playlist ID."""
        playlist_id = self.create_playlist(name, description)
        if track_ids:
            self.add_tracks(playlist_id, track_ids)
        return playlist_id
