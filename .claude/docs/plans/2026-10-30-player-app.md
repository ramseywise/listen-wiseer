# Player app — own "Spotify" on top of Navidrome

Status: PLAN DRAFTED — awaiting review (decisions D1–D4 below)
Branch: `LIS-?-player-app` (cut after repo-audit A/B land; E overlaps — see Sequencing)

## Research

### Where we are (2026-10-30)
- Only UI is Chainlit chat (`src/app/main.py`, 210 lines): agent replies + inline `cl.Audio` (local file or 30s Deezer preview) + Play / Save-playlist actions. No library browser, queue or persistent player.
- Navidrome is in compose (`--profile library`, `deluan/navidrome:0.53.3`, `data/library:/music:ro`), but **`data/library/` does not exist** — nothing to serve. Only writer today is `library/downloads.py` (Jamendo / archive.org CC downloads).
- Playlists: `local_playlists` + `local_playlist_tracks` in DuckDB, 0 rows, track identity = `TrackRef(artist, title, mbid)` — not tied to any playable file.
- `plays` empty (Spotify export not landed) → S3b reranker is data-gated.
- Agent returns structured output already: `agent_response.{message, suggestions, tracks, track_list, playable}` + HITL `__interrupt__` for `confirm_playlist_create`. A non-Chainlit frontend can consume this as-is.
- Node 22 + npm on this machine; no FastAPI in deps yet (Chainlit pulls Starlette/uvicorn transitively).

### Navidrome / Subsonic API surface we need
| Need | Subsonic endpoint |
|---|---|
| Browse | `getArtists`, `getArtist`, `getAlbum`, `getAlbumList2` (recent/newest/frequent/random), `getSong` |
| Search | `search3` |
| Audio | `stream` (supports HTTP Range; `format`/`maxBitRate` for transcode) |
| Art | `getCoverArt` |
| Playlists | `getPlaylists`, `getPlaylist`, `createPlaylist`, `updatePlaylist` (add/remove by index), `deletePlaylist` |
| Favourites | `star` / `unstar`, `getStarred2` |
| Play tracking | `scrobble` (`submission=false` = now playing, `true` = played) |
| Cross-device resume | `savePlayQueue` / `getPlayQueue` |

- Auth = `u` + `t=md5(password+salt)` + `s` per request (or OpenSubsonic API key) — credentials must not reach the browser.
- Navidrome can forward scrobbles to ListenBrainz / Last.fm itself (per-user setting) → closes the "LB CF recs empty" gap once we actually listen through it.
- Subsonic has **no full play-history endpoint** (only play count / last played per song) → if we want `plays` rows, our backend must record them as it proxies `scrobble`.

### Constraints that shape the design
- **DuckDB is single-writer across processes.** Chainlit, MCP server and a new API each opening the DB read-write will collide (`duckdb.IOException` is already handled in `main.py` for this). → The agent must run *inside* the new API process; Chainlit and the API should not both run against the same DB.
- Mixed-source queue: Navidrome stream + Deezer preview are both plain audio URLs (one `<audio>` element). YouTube is an iframe player — can't share the queue cleanly. → YouTube stays "open / embed outside the queue".
- Single user, localhost. No app auth in MVP; bind to `127.0.0.1`.

### Options considered for the assistant panel
| Option | For | Against |
|---|---|---|
| A. Chainlit Copilot widget embedded in the SPA (`window.sendChainlitMessage`, `@cl.on_window_message`) | Reuses `main.py` nearly unchanged | Second server + DuckDB writer; agent→player commands via postMessage; styling fights; no streaming control |
| **B. FastAPI `/api/chat` (SSE) + React chat panel** | One process, agent results become typed "play / queue / add-to-playlist" cards, now-playing context passed in, HITL as a confirm card | Rebuild chat UI (~1 component + message renderer) |

→ **B.** Chainlit stays runnable during migration, retired at the end (D3).

## Plan

### Architecture
```
web/ (Vite + React + TS, Tailwind + shadcn/ui, TanStack Query, Zustand)
  ├── left nav: Home · Search · Library · Playlists
  ├── main: routed views (artist / album / playlist / search / queue)
  ├── right: Assistant panel (collapsible)
  └── bottom: persistent PlayerBar  ← single <audio>, survives route changes
        │  /api/*  (Vite dev proxy; same origin in prod)
src/api/  (FastAPI — BFF, owns Navidrome creds + the only DuckDB writer)
  ├── library.py   → Subsonic proxy (browse, search, cover, stream w/ Range passthrough)
  ├── playlists.py → Subsonic playlists (+ agent save path)
  ├── player.py    → scrobble proxy → Navidrome + DuckDB `plays`; play-queue save/load
  ├── chat.py      → LangGraph agent, SSE
  └── static mount of web/dist in prod
src/sources/subsonic.py → typed Subsonic client (httpx, token auth, OpenSubsonic fields incl. MBID)
src/library/match.py    → TrackRef → Navidrome song id (MBID first, then casefolded artist+title via search3)
Navidrome (docker) ← MUSIC_DIR
```

### Decisions (need sign-off)
- **D1 — Music source.** Navidrome mounts `${MUSIC_DIR:-./data/library}`. Recommend: point it at your real collection (ideally Picard-tagged so MBIDs match); CC downloads go to a `free/` subfolder of the same root. Without files the app is a preview player.
- **D2 — Playlist source of truth = Navidrome.** Playable playlists live in Navidrome (phone apps see them too). Agent `save_playlist` resolves `TrackRef`s via `match.py`; unmatched tracks are returned as "not in library" with preview / YouTube / free-download offers instead of silently dropped. DuckDB `local_playlists` becomes JSPF export only; one-off migration script for any existing rows.
- **D3 — Retire Chainlit** after P4 parity (overrides repo-audit "out of scope: replacing Chainlit"). `make app` → API + web.
- **D4 — Queue persistence** via Subsonic `savePlayQueue` (cross-device), localStorage only for UI prefs (panel open, volume).

### P0 — Library + Navidrome ready (small)
1. Compose: `MUSIC_DIR` env for the Navidrome volume; bump image to current stable (check release notes for breaking config); `ND_` settings for scan interval.
2. `.env.example`: `NAVIDROME_URL`, `NAVIDROME_USER`, `NAVIDROME_PASSWORD`, `MUSIC_DIR`. `utils/config.py` fields.
3. `library/downloads.py`: write under `MUSIC_DIR/free/` (keep `local_path` lookups working).
4. `make doctor`: Navidrome reachable (`ping`), song/album counts via `getScanStatus`.
5. **Gate:** admin user created, library scanned, ≥1 album visible.

### P1 — API skeleton + Subsonic client
1. Deps: `fastapi`, `uvicorn[standard]` (uvicorn already transitive — pin explicitly).
2. `sources/subsonic.py`: auth params, error envelope → `SourceError`, pydantic models (`Artist`, `Album`, `Song`, `Playlist`). MockTransport unit tests (same pattern as other sources).
3. `src/api/app.py` + `library.py`: `/api/artists`, `/api/artists/{id}`, `/api/albums?type=recent|newest|frequent|random`, `/api/albums/{id}`, `/api/search?q=`, `/api/cover/{id}?size=`, `/api/stream/{id}`.
4. Stream proxy: forward `Range`, return 206 + `Content-Range`/`Accept-Ranges`, `StreamingResponse` over httpx stream (seek must work — test with a fixture byte body).
5. `make api` (uvicorn, reload). TestClient tests for each route.

### P2 — Web shell + persistent player
1. Scaffold `web/` (Vite React TS, Tailwind, shadcn, TanStack Query, Zustand, React Router, Vitest). `make web` (dev), `make web-build`. Vite proxy `/api` → `:8000`.
2. Layout: nav / main / assistant slot / PlayerBar; player mounted outside the router outlet.
3. `playerStore` (Zustand): `queue: QueueItem[]`, `index`, `shuffle` (keeps original order for un-shuffle), `repeat: off|all|one`, actions `playNow`, `playNext`, `addToQueue`, `remove`, `move`, `next/prev` (prev restarts if >3s in). `QueueItem = {kind: "library", songId} | {kind: "preview", url, artist, title}`. Pure reducer → Vitest-covered.
4. `<audio>` controller: preload next track, `MediaSession` metadata + handlers (OS media keys / lock screen), keyboard shortcuts (space, ←/→, shift+←/→).
5. Views: Home (recent/frequent/random albums), Search, Artist, Album, Queue panel (drag reorder via dnd-kit). Track row context menu: Play next · Add to queue · Add to playlist · Star.
6. Scrobble client: `submission=false` on start, `true` at ≥50% or 4 min.

### P3 — Playlists + favourites
1. `/api/playlists` CRUD on Subsonic; `PATCH` for add / remove / reorder (Subsonic reorder = rewrite: `createPlaylist` with `playlistId` + full song list).
2. Views: playlist list in nav, playlist page (play all, shuffle, drag reorder, remove), "New playlist" dialog, add-to-playlist submenu. Liked Songs = `getStarred2`.
3. `/api/player/scrobble` → Navidrome + insert into DuckDB `plays` (`ts`, `track_key`, artist/title/album, `ms_played`, `skipped` = advanced before 30s). Schema: add nullable `navidrome_id`, `source='navidrome'`.
4. `/api/player/queue` GET/PUT → `getPlayQueue`/`savePlayQueue` (debounced from the store).
5. Migration script: DuckDB `local_playlists` → Navidrome via `match.py` (report unmatched).

### P4 — Assistant panel
1. `library/match.py`: MBID → `search3` artist+title (casefold, strip "feat."/remaster suffixes) → confidence; cache in DuckDB `track_xref.navidrome_id`. Fixture-tested.
2. `/api/chat` (POST, SSE): `thread_id` per panel session; streams `token` / `tracks` / `interrupt` / `done` events from `graph.astream`. Each track in `agent_response.tracks` enriched with `navidrome_id` (via match) else `PlayableTrack` fallback.
3. Request carries `now_playing` + first N queue items → injected as a context message so "more like this" / "what is this?" work.
4. Agent `save_playlist` tool → Navidrome via D2; HITL interrupt rendered as a confirm card (`/api/chat/resume`).
5. Panel UI: markdown messages, suggestion chips, track cards (▶ play · + queue · add-to-playlist · "not in library" → preview / YouTube / find free download), "Queue all".
6. Parity check vs Chainlit (welcome, suggestions, play, save, HITL) → D3: remove `src/app/`, Chainlit dep, `.chainlit/`.

### P5 — Discovery in the player (uses what exists)
1. "Radio" from current track/artist: `recommend/engine` + `discover.py` candidates, filtered to library matches first, previews after. Endless-queue toggle.
2. Discover page: `discover_tracks` output as sections ("in your library you haven't played", "new to you — previews", "free to download").
3. Feeds S3b: `plays` from P3.3 is the label source the reranker has been waiting on.

### P6 — Packaging
1. Compose `api` service (replaces `app`): multi-stage — node build of `web/` → copied into Python image, FastAPI serves `web/dist`. Depends on Navidrome. Coordinate with repo-audit E (MCP + Dockerfile changes).
2. MCP server opens DuckDB read-only (or via the API) to avoid the writer clash.
3. `make infra-up && make infra-smoke`: stream one track end to end.

### Sequencing
- Repo-audit A/B first (doctor, `.env.example`, README) — P0 edits the same files.
- Audit E (Dockerfile/compose) and P6 touch the same files → do E before P6, or fold E into P6.
- Audit C2 (drop torch from default install) is independent but makes the API image much smaller.
- P0 → P1 → P2 are strictly ordered; P3 and P4 can run in parallel after P2.

### Verify
- Each phase: unit tests (pytest for `api/`, `sources/subsonic.py`, `match.py`; Vitest for `playerStore`), `make lint`.
- P2 manual: play album → navigate around → playback uninterrupted; seek mid-track (Range); media keys.
- P4 manual: "play something like what's on" → queued library tracks; save playlist → appears in Navidrome web UI and Symfonium.

### Out of scope
- Multi-user / auth, mobile app (Subsonic clients cover phones), offline caching, lyrics, gapless/crossfade (revisit after P2), YouTube audio extraction (ToS).

### Open risks
- Match quality without MBID tags → lots of "not in library" false negatives. Mitigation: tag with Picard; log match confidence; manual "link to library track" later.
- Transcoding CPU on big FLAC libraries — default `format=raw`, opt-in `maxBitRate`.
