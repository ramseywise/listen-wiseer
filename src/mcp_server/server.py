"""
MCP server exposing Spotify tools for LLM agents.
Run with: uv run python src/mcp_server/server.py
"""

import duckdb
from mcp.server.fastmcp import FastMCP

from paths import DATA_DIR, MODELS_DIR
from recommend.engine import RecommendationEngine
from recommend.schemas import RecommendRequest
from spotify.client import SpotifyClient
from spotify.fetch import (
    fetch_artist_albums,
    fetch_artist_info,
    fetch_artist_top_tracks,
    fetch_audio_features,
    fetch_my_playlists,
    fetch_playlist_tracks,
    fetch_recently_played,
    fetch_related_artists,
    fetch_spotify_recommendations,
    fetch_top_artists,
    fetch_top_tracks,
)
from spotify.playback import get_playback_state, play_tracks, queue_track as queue_track_fn
from spotify.write import SpotifyActions
from utils.exceptions import SpotifyAuthError
from utils.logging import get_logger

log = get_logger(__name__)

mcp = FastMCP("listen-wiseer")

try:
    _engine: RecommendationEngine | None = RecommendationEngine(
        models_dir=MODELS_DIR,
        data_dir=DATA_DIR,
    )
except (FileNotFoundError, duckdb.IOException) as exc:
    _engine = None
    log.warning("mcp.engine.unavailable", error=str(exc))


@mcp.tool()
def get_playlist_tracks(playlist_id: str) -> str:
    """Get the list of tracks in a Spotify playlist by playlist ID."""
    sp = SpotifyClient()
    tracks = fetch_playlist_tracks(sp, playlist_id)
    return "\n".join(f"{t.name} — {', '.join(t.artist_names)}" for t in tracks)


@mcp.tool()
def get_track_features(track_id: str) -> str:
    """Get audio features for a Spotify track by track ID."""
    sp = SpotifyClient()
    features = fetch_audio_features(sp, [track_id])
    return str(features[0].model_dump()) if features else f"No features found for {track_id}"


@mcp.tool()
def get_recently_played(limit: int = 20) -> str:
    """Get the current user's recently played tracks."""
    sp = SpotifyClient()
    tracks = fetch_recently_played(sp, limit=limit)
    return "\n".join(f"{t.name} — {', '.join(t.artist_names)}" for t in tracks)


@mcp.tool()
def search_tracks(query: str, limit: int = 10) -> str:
    """Search Spotify for tracks matching a query."""
    from utils.exceptions import SpotifyClientError

    sp = SpotifyClient()
    try:
        results = sp.search(q=query, type="track", limit=limit)
        items = results["tracks"]["items"]
    except (SpotifyClientError, KeyError) as e:
        return f"Search failed: {e}"
    return "\n".join(
        f"{t['name']} — {', '.join(a['name'] for a in t['artists'])} [{t['id']}]" for t in items
    )


def _format_result(result) -> str:
    if not result.track_uris:
        return result.explanation
    lines = [result.explanation, ""]
    for i, (name, uri) in enumerate(zip(result.track_names, result.track_uris, strict=False), 1):
        lines.append(f"{i}. {name} [{uri}]")
    return "\n".join(lines)


@mcp.tool()
def recommend_similar_tracks(track_id: str, k: int = 10) -> str:
    """Find tracks with similar audio characteristics to a given Spotify track ID."""
    if _engine is None:
        return "Recommendation models not trained yet. Run: make train"
    result = _engine.recommend(RecommendRequest(request_type="track", seed_id=track_id, k=k))
    return _format_result(result)


@mcp.tool()
def recommend_for_artist(artist_id: str, k: int = 10) -> str:
    """Find tracks matching an artist's sonic profile using their Spotify artist ID."""
    if _engine is None:
        return "Recommendation models not trained yet. Run: make train"
    result = _engine.recommend(RecommendRequest(request_type="artist", seed_id=artist_id, k=k))
    return _format_result(result)


@mcp.tool()
def recommend_for_playlist(playlist_id: str, k: int = 10) -> str:
    """Find tracks to add to a Spotify playlist based on its audio fingerprint."""
    if _engine is None:
        return "Recommendation models not trained yet. Run: make train"
    result = _engine.recommend(RecommendRequest(request_type="playlist", seed_id=playlist_id, k=k))
    return _format_result(result)


@mcp.tool()
def recommend_by_genre(genre_name: str, k: int = 10) -> str:
    """Find tracks in a genre zone using ENOA spatial map (e.g. 'zouk', 'bossa nova', 'house')."""
    if _engine is None:
        return "Recommendation models not trained yet. Run: make train"
    result = _engine.recommend(RecommendRequest(request_type="genre", seed_id=genre_name, k=k))
    return _format_result(result)


@mcp.tool()
def get_top_tracks(time_range: str = "medium_term", limit: int = 20) -> str:
    """Get the user's top Spotify tracks. time_range: short_term, medium_term, long_term."""
    sp = SpotifyClient()
    tracks = fetch_top_tracks(sp, time_range=time_range, limit=limit)
    labels = {"short_term": "past 4 weeks", "medium_term": "past 6 months", "long_term": "all time"}
    label = labels.get(time_range, time_range)
    if not tracks:
        return "No top tracks found."
    lines = [f"Top tracks ({label}):"]
    lines.extend(f"{i}. {t.name} — {', '.join(t.artist_names)} [{t.id}]" for i, t in enumerate(tracks, 1))
    return "\n".join(lines)


@mcp.tool()
def get_top_artists(time_range: str = "medium_term", limit: int = 20) -> str:
    """Get the user's top Spotify artists. time_range: short_term, medium_term, long_term."""
    sp = SpotifyClient()
    artists = fetch_top_artists(sp, time_range=time_range, limit=limit)
    labels = {"short_term": "past 4 weeks", "medium_term": "past 6 months", "long_term": "all time"}
    label = labels.get(time_range, time_range)
    if not artists:
        return "No top artists found."
    lines = [f"Top artists ({label}):"]
    lines.extend(
        f"{i}. {a['name']} — {', '.join(a['genres'][:3]) or 'unknown'} (pop: {a['popularity']}) [{a['id']}]"
        for i, a in enumerate(artists, 1)
    )
    return "\n".join(lines)


@mcp.tool()
def get_artist_info(artist_id: str) -> str:
    """Get Spotify artist metadata: name, genres, popularity, follower count."""
    sp = SpotifyClient()
    info = fetch_artist_info(sp, artist_id)
    return (
        f"Artist: {info['name']}\n"
        f"Genres: {', '.join(info['genres'][:5]) or 'unknown'}\n"
        f"Popularity: {info['popularity']}/100\n"
        f"Followers: {info['followers']:,}"
    )


@mcp.tool()
def get_artist_top_tracks(artist_id: str) -> str:
    """Get an artist's top 10 Spotify tracks by artist ID."""
    sp = SpotifyClient()
    tracks = fetch_artist_top_tracks(sp, artist_id)
    if not tracks:
        return f"No top tracks found for {artist_id}."
    return "\n".join(f"{i}. {t.name} [{t.id}]" for i, t in enumerate(tracks, 1))


@mcp.tool()
def get_artist_albums(artist_id: str) -> str:
    """Get an artist's discography (albums and singles) by artist ID."""
    sp = SpotifyClient()
    albums = fetch_artist_albums(sp, artist_id)
    if not albums:
        return f"No albums found for {artist_id}."
    return "\n".join(
        f"{i}. {a['name']} ({a['type']}, {a['release_date']}, {a['total_tracks']} tracks) [{a['id']}]"
        for i, a in enumerate(albums, 1)
    )


@mcp.tool()
def get_related_artists(artist_id: str) -> str:
    """Get up to 20 artists that sound similar to the given Spotify artist ID."""
    sp = SpotifyClient()
    artists = fetch_related_artists(sp, artist_id)
    if not artists:
        return f"No related artists found for {artist_id}."
    return "\n".join(
        f"- {a['name']} ({', '.join(a['genres']) or 'unknown genre'}) [{a['id']}]"
        for a in artists
    )


@mcp.tool()
def get_user_playlists() -> str:
    """List all of the user's Spotify playlists with IDs."""
    sp = SpotifyClient()
    playlists = fetch_my_playlists(sp)
    if not playlists:
        return "No playlists found."
    return "\n".join(
        f"{i}. {p['name']} ({p.get('tracks', {}).get('total', '?')} tracks) [{p['id']}]"
        for i, p in enumerate(playlists, 1)
    )


@mcp.tool()
def get_spotify_recommendations(
    seed_track_ids: str = "",
    seed_artist_ids: str = "",
    seed_genres: str = "",
    limit: int = 20,
) -> str:
    """Get Spotify's native recommendations. Pass comma-separated IDs/genre names. Total seeds must be 1-5."""
    sp = SpotifyClient()
    tracks = fetch_spotify_recommendations(
        sp,
        seed_tracks=[x for x in seed_track_ids.split(",") if x] or None,
        seed_artists=[x for x in seed_artist_ids.split(",") if x] or None,
        seed_genres=[x for x in seed_genres.split(",") if x] or None,
        limit=limit,
    )
    if not tracks:
        return "No recommendations found."
    lines = ["Spotify recommendations:"]
    lines.extend(f"{i}. {t.name} — {', '.join(t.artist_names)} [{t.id}]" for i, t in enumerate(tracks, 1))
    return "\n".join(lines)


# --- Write tools ---


@mcp.tool()
def create_playlist(name: str, description: str = "") -> str:
    """Create a new private Spotify playlist. Returns the playlist ID and URL."""
    try:
        sp = SpotifyClient()
        actions = SpotifyActions(sp)
        playlist_id = actions.create_playlist(name, description)
    except SpotifyAuthError:
        return "Auth expired — run `make auth` to re-authenticate."
    return f"Created playlist '{name}': https://open.spotify.com/playlist/{playlist_id}"


@mcp.tool()
def add_tracks_to_playlist(playlist_id: str, track_ids: list[str]) -> str:
    """Add tracks to an existing Spotify playlist. Accepts a list of track IDs."""
    if not track_ids:
        return "No track IDs provided."
    try:
        sp = SpotifyClient()
        actions = SpotifyActions(sp)
        actions.add_tracks(playlist_id, track_ids)
    except SpotifyAuthError:
        return "Auth expired — run `make auth` to re-authenticate."
    return f"Added {len(track_ids)} tracks to playlist {playlist_id}."


@mcp.tool()
def create_playlist_with_tracks(
    name: str, track_ids: list[str], description: str = ""
) -> str:
    """Create a new Spotify playlist and populate it with tracks in one step."""
    if not track_ids:
        return "No track IDs provided."
    try:
        sp = SpotifyClient()
        actions = SpotifyActions(sp)
        playlist_id = actions.create_playlist_with_tracks(name, track_ids, description)
    except SpotifyAuthError:
        return "Auth expired — run `make auth` to re-authenticate."
    return (
        f"Created playlist '{name}' with {len(track_ids)} tracks: "
        f"https://open.spotify.com/playlist/{playlist_id}"
    )


# --- Playback tools ---


@mcp.tool()
def play_track(track_id: str) -> str:
    """Start playback of a specific track on the user's active Spotify device."""
    try:
        sp = SpotifyClient()
        play_tracks(sp, [track_id])
    except SpotifyAuthError:
        return "Auth expired — run `make auth` to re-authenticate."
    return f"Playing track {track_id}."


@mcp.tool()
def queue_track(track_id: str) -> str:
    """Add a track to the user's Spotify playback queue."""
    try:
        sp = SpotifyClient()
        queue_track_fn(sp, track_id)
    except SpotifyAuthError:
        return "Auth expired — run `make auth` to re-authenticate."
    return f"Queued track {track_id}."


@mcp.tool()
def get_current_playback() -> str:
    """Get the user's current Spotify playback state (track, device, progress)."""
    try:
        sp = SpotifyClient()
        state = get_playback_state(sp)
    except SpotifyAuthError:
        return "Auth expired — run `make auth` to re-authenticate."
    if state is None:
        return "No active playback session. Open Spotify on a device first."
    track = state.get("item", {})
    device = state.get("device", {})
    progress_ms = state.get("progress_ms", 0)
    duration_ms = track.get("duration_ms", 1)
    pct = int(progress_ms / duration_ms * 100) if duration_ms else 0
    artists = ", ".join(a["name"] for a in track.get("artists", []))
    return (
        f"Now playing: {track.get('name', '?')} — {artists}\n"
        f"Album: {track.get('album', {}).get('name', '?')}\n"
        f"Device: {device.get('name', '?')} ({device.get('type', '?')})\n"
        f"Progress: {pct}% | {'Playing' if state.get('is_playing') else 'Paused'}"
    )


if __name__ == "__main__":
    mcp.run()
