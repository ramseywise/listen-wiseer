from __future__ import annotations

from agent.tools.memory import manage_taste_memory, search_taste_memory
from agent.tools.recommend import (
    recommend_by_genre,
    recommend_for_artist,
    recommend_for_playlist,
    recommend_similar_tracks,
)
from agent.tools.spotify_read import (
    get_artist_albums_tool,
    get_artist_info_tool,
    get_artist_top_tracks_tool,
    get_recently_played_tool,
    get_related_artists_tool,
    get_spotify_recommendations_tool,
    get_taste_analysis_tool,
    get_top_artists_tool,
    get_top_tracks_tool,
    get_user_playlists_tool,
    search_tracks_tool,
)
from agent.tools.spotify_write import create_playlist_tool
from agent.tools.web_search import get_artist_context_tool, get_genre_context_tool

ALL_TOOLS = [
    # Recommendations (ENOA corpus)
    recommend_similar_tracks,
    recommend_for_artist,
    recommend_by_genre,
    recommend_for_playlist,
    # Spotify read — discovery & exploration
    get_spotify_recommendations_tool,
    get_top_tracks_tool,
    get_top_artists_tool,
    get_recently_played_tool,
    get_user_playlists_tool,
    # Spotify read — artist deep dives
    search_tracks_tool,
    get_artist_info_tool,
    get_related_artists_tool,
    get_artist_top_tracks_tool,
    get_artist_albums_tool,
    # Context & memory
    get_artist_context_tool,
    get_genre_context_tool,
    get_taste_analysis_tool,
    manage_taste_memory,
    search_taste_memory,
    # Spotify write (HITL)
    create_playlist_tool,
]

__all__ = [
    "ALL_TOOLS",
    "recommend_similar_tracks",
    "recommend_for_artist",
    "recommend_by_genre",
    "recommend_for_playlist",
    "get_spotify_recommendations_tool",
    "get_top_tracks_tool",
    "get_top_artists_tool",
    "get_recently_played_tool",
    "get_user_playlists_tool",
    "search_tracks_tool",
    "get_artist_info_tool",
    "get_related_artists_tool",
    "get_artist_top_tracks_tool",
    "get_artist_albums_tool",
    "get_artist_context_tool",
    "get_genre_context_tool",
    "get_taste_analysis_tool",
    "create_playlist_tool",
    "manage_taste_memory",
    "search_taste_memory",
]
