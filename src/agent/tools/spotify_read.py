from __future__ import annotations

from langchain_core.tools import StructuredTool

from spotify.client import SpotifyClient
from spotify.fetch import (
    fetch_artist_albums,
    fetch_artist_info,
    fetch_artist_top_tracks,
    fetch_my_playlists,
    fetch_recently_played,
    fetch_related_artists,
    fetch_spotify_recommendations,
    fetch_top_artists,
    fetch_top_tracks,
)
from utils.logging import get_logger

log = get_logger(__name__)

_client: SpotifyClient | None = None


def _get_client() -> SpotifyClient:
    global _client  # noqa: PLW0603
    if _client is None:
        _client = SpotifyClient()
    return _client


def _get_recently_played(limit: int = 20) -> str:
    try:
        tracks = fetch_recently_played(_get_client(), limit=limit)
        if not tracks:
            return "No recently played tracks found."
        return "\n".join(
            f"{i}. {t.name} — {', '.join(t.artist_names)} [{t.id}]"
            for i, t in enumerate(tracks, 1)
        )
    except Exception as exc:
        log.error("agent.tools.recently_played.failed", error=str(exc))
        return f"Failed to fetch recently played: {exc}"


get_recently_played_tool = StructuredTool.from_function(
    _get_recently_played,
    name="get_recently_played",
    description="Get the user's recently played tracks from Spotify.",
)


def _search_tracks(query: str, limit: int = 10) -> str:
    from utils.exceptions import SpotifyClientError

    try:
        results = _get_client().search(q=query, type="track", limit=limit)
        items = results["tracks"]["items"]
    except (SpotifyClientError, KeyError) as exc:
        log.error("agent.tools.search.failed", error=str(exc))
        return f"Search failed: {exc}"
    if not items:
        return f"No tracks found for '{query}'."
    return "\n".join(
        f"{i}. {t['name']} — {', '.join(a['name'] for a in t['artists'])} [{t['id']}]"
        for i, t in enumerate(items, 1)
    )


search_tracks_tool = StructuredTool.from_function(
    _search_tracks,
    name="search_tracks",
    description="Search Spotify for tracks matching a text query.",
)


def _get_related_artists(artist_id: str) -> str:
    from utils.exceptions import SpotifyClientError

    try:
        artists = fetch_related_artists(_get_client(), artist_id)
        if not artists:
            return f"No related artists found for {artist_id}"
        return "\n".join(
            f"- {a['name']} ({', '.join(a['genres']) or 'unknown genre'})"
            for a in artists
        )
    except SpotifyClientError as exc:
        log.warning("tool.get_related_artists.failed", error=str(exc))
        return f"Failed to fetch related artists: {exc}"


get_related_artists_tool = StructuredTool.from_function(
    _get_related_artists,
    name="get_related_artists",
    description=(
        "Find artists that sound similar to a given Spotify artist ID. "
        "Use for 'who sounds like X?' or 'artists similar to X' queries. "
        "Requires a Spotify artist ID — use search_tracks first to find the ID."
    ),
)

_TIME_RANGE_LABELS = {
    "short_term": "past 4 weeks",
    "medium_term": "past 6 months",
    "long_term": "all time",
}


def _get_top_tracks(time_range: str = "medium_term", limit: int = 20) -> str:
    try:
        tracks = fetch_top_tracks(_get_client(), time_range=time_range, limit=limit)
        if not tracks:
            return "No top tracks found."
        label = _TIME_RANGE_LABELS.get(time_range, time_range)
        lines = [f"Your top tracks ({label}):"]
        lines.extend(
            f"{i}. {t.name} — {', '.join(t.artist_names)} [{t.id}]"
            for i, t in enumerate(tracks, 1)
        )
        return "\n".join(lines)
    except Exception as exc:
        log.error("agent.tools.top_tracks.failed", error=str(exc))
        return f"Failed to fetch top tracks: {exc}"


get_top_tracks_tool = StructuredTool.from_function(
    _get_top_tracks,
    name="get_top_tracks",
    description=(
        "Get the user's top Spotify tracks for a time range. "
        "time_range: 'short_term' (~4 weeks), 'medium_term' (~6 months), 'long_term' (all time). "
        "Use for 'what have I been listening to', 'my top tracks this month', taste analysis."
    ),
)


def _get_top_artists(time_range: str = "medium_term", limit: int = 20) -> str:
    try:
        artists = fetch_top_artists(_get_client(), time_range=time_range, limit=limit)
        if not artists:
            return "No top artists found."
        label = _TIME_RANGE_LABELS.get(time_range, time_range)
        lines = [f"Your top artists ({label}):"]
        lines.extend(
            f"{i}. {a['name']} — {', '.join(a['genres'][:3]) or 'unknown genre'} "
            f"(popularity: {a['popularity']}) [{a['id']}]"
            for i, a in enumerate(artists, 1)
        )
        return "\n".join(lines)
    except Exception as exc:
        log.error("agent.tools.top_artists.failed", error=str(exc))
        return f"Failed to fetch top artists: {exc}"


get_top_artists_tool = StructuredTool.from_function(
    _get_top_artists,
    name="get_top_artists",
    description=(
        "Get the user's top Spotify artists for a time range. "
        "time_range: 'short_term' (~4 weeks), 'medium_term' (~6 months), 'long_term' (all time). "
        "Use for 'my top artists', 'what genres am I into', taste analysis."
    ),
)


def _get_artist_info(artist_id: str) -> str:
    try:
        info = fetch_artist_info(_get_client(), artist_id)
        genres = ", ".join(info["genres"][:5]) or "unknown"
        return (
            f"Artist: {info['name']}\n"
            f"Genres: {genres}\n"
            f"Popularity: {info['popularity']}/100\n"
            f"Followers: {info['followers']:,}\n"
            f"ID: {info['id']}"
        )
    except Exception as exc:
        log.error("agent.tools.artist_info.failed", error=str(exc))
        return f"Failed to fetch artist info: {exc}"


get_artist_info_tool = StructuredTool.from_function(
    _get_artist_info,
    name="get_artist_info",
    description=(
        "Get metadata for a Spotify artist: genres, popularity score, follower count. "
        "Requires a Spotify artist ID — use search_tracks first to resolve the ID. "
        "Use before get_artist_context to get structured metadata alongside the narrative bio."
    ),
)


def _get_artist_top_tracks(artist_id: str) -> str:
    try:
        tracks = fetch_artist_top_tracks(_get_client(), artist_id)
        if not tracks:
            return f"No top tracks found for artist {artist_id}."
        return "\n".join(
            f"{i}. {t.name} [{t.id}]" for i, t in enumerate(tracks, 1)
        )
    except Exception as exc:
        log.error("agent.tools.artist_top_tracks.failed", error=str(exc))
        return f"Failed to fetch artist top tracks: {exc}"


get_artist_top_tracks_tool = StructuredTool.from_function(
    _get_artist_top_tracks,
    name="get_artist_top_tracks",
    description=(
        "Get an artist's top 10 tracks on Spotify. "
        "Requires a Spotify artist ID. "
        "Use for 'show me X's best songs', discography entry point, seeding recommendations."
    ),
)


def _get_artist_albums(artist_id: str) -> str:
    try:
        albums = fetch_artist_albums(_get_client(), artist_id)
        if not albums:
            return f"No albums found for artist {artist_id}."
        return "\n".join(
            f"{i}. {a['name']} ({a['type']}, {a['release_date']}, {a['total_tracks']} tracks) [{a['id']}]"
            for i, a in enumerate(albums, 1)
        )
    except Exception as exc:
        log.error("agent.tools.artist_albums.failed", error=str(exc))
        return f"Failed to fetch artist albums: {exc}"


get_artist_albums_tool = StructuredTool.from_function(
    _get_artist_albums,
    name="get_artist_albums",
    description=(
        "Get an artist's discography (albums and singles). "
        "Requires a Spotify artist ID. "
        "Use for 'show me X's albums', 'what has X released', discography deep dives."
    ),
)


def _get_user_playlists() -> str:
    try:
        playlists = fetch_my_playlists(_get_client())
        if not playlists:
            return "No playlists found."
        return "\n".join(
            f"{i}. {p['name']} ({p.get('tracks', {}).get('total', '?')} tracks) [{p['id']}]"
            for i, p in enumerate(playlists, 1)
        )
    except Exception as exc:
        log.error("agent.tools.user_playlists.failed", error=str(exc))
        return f"Failed to fetch playlists: {exc}"


get_user_playlists_tool = StructuredTool.from_function(
    _get_user_playlists,
    name="get_user_playlists",
    description=(
        "List all of the user's Spotify playlists with their IDs. "
        "Use when the user asks to see their playlists, or to look up a playlist ID "
        "before calling recommend_for_playlist."
    ),
)


def _get_spotify_recommendations(
    seed_track_ids: list[str] | None = None,
    seed_artist_ids: list[str] | None = None,
    seed_genres: list[str] | None = None,
    limit: int = 20,
) -> str:
    try:
        tracks = fetch_spotify_recommendations(
            _get_client(),
            seed_tracks=seed_track_ids,
            seed_artists=seed_artist_ids,
            seed_genres=seed_genres,
            limit=limit,
        )
        if not tracks:
            return "No recommendations found."
        lines = ["Spotify recommendations:"]
        lines.extend(
            f"{i}. {t.name} — {', '.join(t.artist_names)} [{t.id}]"
            for i, t in enumerate(tracks, 1)
        )
        return "\n".join(lines)
    except Exception as exc:
        log.error("agent.tools.spotify_recommendations.failed", error=str(exc))
        return f"Failed to fetch Spotify recommendations: {exc}"


get_spotify_recommendations_tool = StructuredTool.from_function(
    _get_spotify_recommendations,
    name="get_spotify_recommendations",
    description=(
        "Get Spotify's native recommendations seeded by tracks, artists, or genres. "
        "Total seeds across all inputs must be 1–5. "
        "Use for discovery (finding new music) or as a fallback when a track/artist "
        "is not in the local corpus. Complements our ENOA-based recommender."
    ),
)
