from __future__ import annotations

from langchain_core.tools import StructuredTool
from langgraph.types import interrupt

from spotify.client import SpotifyClient
from spotify.write import SpotifyActions
from utils.logging import get_logger

log = get_logger(__name__)

_actions: SpotifyActions | None = None


def _get_actions() -> SpotifyActions:
    global _actions  # noqa: PLW0603
    if _actions is None:
        _actions = SpotifyActions(SpotifyClient())
    return _actions


def _create_playlist(name: str, track_uris: list[str], description: str = "") -> str:
    """Create a Spotify playlist after user confirms."""
    confirmed = interrupt(
        {
            "type": "confirm_playlist_create",
            "name": name,
            "track_count": len(track_uris),
            "description": description,
        }
    )
    if not confirmed:
        return f"Playlist '{name}' creation cancelled."
    try:
        playlist_id = _get_actions().create_playlist_with_tracks(name, track_uris, description)
        log.info("agent.tools.create_playlist.success", playlist_id=playlist_id, name=name)
        return (
            f"Created playlist '{name}' with {len(track_uris)} tracks. "
            f"Spotify playlist ID: {playlist_id}"
        )
    except Exception as exc:
        log.error("agent.tools.create_playlist.failed", error=str(exc))
        return f"Failed to create playlist: {exc}"


create_playlist_tool = StructuredTool.from_function(
    _create_playlist,
    name="create_playlist",
    description=(
        "Create a new Spotify playlist populated with the given track URIs. "
        "Call only when the user explicitly asks to save or create a playlist. "
        "Always interrupts to ask user for confirmation before writing to Spotify."
    ),
)
