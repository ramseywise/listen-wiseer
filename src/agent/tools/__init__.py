from __future__ import annotations

from agent.tools.discover import (
    discover_tracks_tool,
    list_playlists_tool,
    play_track_tool,
    save_playlist_tool,
)
from agent.tools.downloads import download_track_tool, find_free_downloads_tool
from agent.tools.memory import manage_taste_memory, search_taste_memory
from agent.tools.music import (
    get_artist_albums_tool,
    get_artist_info_tool,
    get_artist_top_tracks_tool,
    get_recently_played_tool,
    get_related_artists_tool,
    get_taste_analysis_tool,
    get_top_artists_tool,
    get_top_tracks_tool,
    search_tracks_tool,
)
from agent.tools.recommend import (
    recommend_by_genre,
    recommend_for_artist,
    recommend_for_playlist,
    recommend_similar_tracks,
)
from agent.tools.web_search import get_artist_context_tool, get_genre_context_tool

ALL_TOOLS = [
    # Open-world discovery, free playback
    discover_tracks_tool,
    play_track_tool,
    # Legal downloads into the local library
    find_free_downloads_tool,
    download_track_tool,
    # Recommendations (ENOA corpus)
    recommend_similar_tracks,
    recommend_for_artist,
    recommend_by_genre,
    recommend_for_playlist,
    # Listening history (local plays)
    get_top_tracks_tool,
    get_top_artists_tool,
    get_recently_played_tool,
    get_taste_analysis_tool,
    # Artist / track lookups
    search_tracks_tool,
    get_artist_info_tool,
    get_related_artists_tool,
    get_artist_top_tracks_tool,
    get_artist_albums_tool,
    # Context & memory
    get_artist_context_tool,
    get_genre_context_tool,
    manage_taste_memory,
    search_taste_memory,
    # Local playlists (save is HITL)
    list_playlists_tool,
    save_playlist_tool,
]

__all__ = [
    "ALL_TOOLS",
    "discover_tracks_tool",
    "play_track_tool",
    "find_free_downloads_tool",
    "download_track_tool",
    "save_playlist_tool",
    "list_playlists_tool",
    "recommend_similar_tracks",
    "recommend_for_artist",
    "recommend_by_genre",
    "recommend_for_playlist",
    "get_top_tracks_tool",
    "get_top_artists_tool",
    "get_recently_played_tool",
    "get_taste_analysis_tool",
    "search_tracks_tool",
    "get_artist_info_tool",
    "get_related_artists_tool",
    "get_artist_top_tracks_tool",
    "get_artist_albums_tool",
    "get_artist_context_tool",
    "get_genre_context_tool",
    "manage_taste_memory",
    "search_taste_memory",
]
