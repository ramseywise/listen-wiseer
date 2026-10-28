Test plan
- rm .spotify_cache && make auth to pick up new playback scopes
- Open fresh Claude Code session in repo, run /mcp — verify listen-wiseer shows 22 tools
- Ask "What are my top tracks?" → verify get_top_tracks fires
- Ask for a recommendation → verify recommend_similar_tracks fires
- Ask to create a playlist with results → confirm tool call → verify playlist in Spotify
- Ask to play a track → verify playback starts on active device
- Delete .spotify_cache, retry a tool → verify friendly error message
- make test-integration passes (15 new tests)
