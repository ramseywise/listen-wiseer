"""
Spotify playback control — play, queue, get state via Connect API.
"""

from spotify.client import SpotifyClient


def play_tracks(client: SpotifyClient, track_ids: list[str]) -> None:
    """Start playback of specific tracks on the user's active device."""
    uris = [f"spotify:track:{t}" if not t.startswith("spotify:") else t for t in track_ids]
    client.put("me/player/play", json={"uris": uris})


def queue_track(client: SpotifyClient, track_id: str) -> None:
    """Add a single track to the user's playback queue."""
    uri = f"spotify:track:{track_id}" if not track_id.startswith("spotify:") else track_id
    client.post(f"me/player/queue?uri={uri}")


def get_playback_state(client: SpotifyClient) -> dict | None:
    """Get current playback state. Returns None if nothing is playing."""
    result = client.get("me/player")
    if not result:
        return None
    return result
