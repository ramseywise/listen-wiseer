# Free music stack — move off Spotify

Status: IN PROGRESS — S0–S2, S3a, S4, S5 done; next S6 (needs Jamendo client_id)
Branch: `free-music-stack`

## Research

### Why
- Spotify Dev Mode apps require the **owner to have Premium** since 2026-03-09; app stops working if it lapses. Subscription cancelled → the whole `src/spotify/` integration is dead, not just the deprecated endpoints.
- Already dead before that: `recommendations`, `related-artists`, `audio-features` (Nov 2024); artist top-tracks / albums on the Feb 2026 removal list; `playlists/{id}/tracks` renamed to `/items`.
- Playback (`me/player/*`) always needed Premium.

### Data on hand (2026-10-28)
- `infrastructure/db/listen_wiseer.db` — schema only, **0 rows** in every table (HEAD copy too).
- `data/archived/` (bootstrap CSVs) — not on this machine.
- `data/cache/corpus_features.parquet` — 2,182 tracks: Spotify ID, track name, audio features, ENOA genre, t2v embeddings. **No artist names.**
- MusicBrainz URL lookup by Spotify track URL: **1/25** sample hit → not viable as primary ID bridge.
- → **Spotify privacy export ("Extended streaming history") is the bridge**: `spotify_track_uri` + artist + title per play. `ListeningHistoryEntry` (`utils/schemas.py`) and `etl.loader.load_listening_history` already parse it.

### Free replacements (probed live 2026-10-28)
| Need | Source | Auth | Notes |
|---|---|---|---|
| IDs + metadata + genres + artist rels | MusicBrainz WS/2 | none (UA required) | 1 req/s. Recording search by artist+title works (score 100). |
| Collaborative recs, radio | ListenBrainz | **user token now required, even for reads** | `/1/cf/recommendation/user/{u}/recording`, `/1/explore/lb-radio`, `/1/metadata/lookup`. Import Spotify export via LB web UI. |
| Similar tracks/artists | Last.fm | API key (activation pending) | `track.getSimilar`, `artist.getSimilar`. Client exists in `etl/lastfm.py` (tags only). |
| Previews, ISRC, related artists | Deezer | none | `/search`, `/artist/{id}/related`; 30s `preview` mp3 URLs (signed, expire). |
| Full playback | YouTube | link: none; embed lookup: Data API key (≈100 searches/day free) | Embed iframe = ToS-clean. No yt-dlp. |
| Audio features | AcousticBrainz dumps | none | Frozen 2022; keyed by recording MBID. Optional. |

## Plan

**ID strategy:** MusicBrainz recording MBID is canonical. Keep `spotify_id`, `deezer_id`, `isrc` as cross-ref columns. Corpus rows keep their Spotify ID as join key into the export.

### S0 — Cleanup ✓
- Branch `free-music-stack`; 23 completed plan docs → `.claude/docs/archive/plans/`.

### S1 — `src/sources/` adapter layer ✓
- Done 2026-10-28: 43 unit tests (MockTransport), live smoke OK for MusicBrainz + Deezer. LB Radio verified live 2026-10-28 (35 tracks w/ MBIDs). CF recs empty until LB has listen history.
- Finding: MB recording *search* omits ISRCs → S2 needs `recording/{mbid}?inc=isrcs` lookup if ISRC wanted.
- Added `search_artist` (name → MBID) for agent use.
- `sources/http.py` — shared httpx client: UA, per-host min interval, retry on 429/503 w/ Retry-After.
- `sources/schemas.py` — `Recording`, `ArtistInfo`, `SimilarItem`, `PlayableTrack` (pydantic).
- `sources/musicbrainz.py` — `search_recording(artist, title)`, `lookup_spotify_track(id)`, `get_artist(mbid)` (genres, tags, member/influence rels).
- `sources/deezer.py` — `find_track(artist, title)` → preview/link/isrc; `related_artists(name)`.
- `sources/lastfm.py` — `similar_tracks`, `similar_artists`.
- `sources/listenbrainz.py` — `cf_recommendations(user)`, `lb_radio(prompt, mode)`; no-op + warning without token.
- `sources/youtube.py` — search link always; embed video id iff `YOUTUBE_API_KEY`.
- Config: `musicbrainz_user_agent`, `listenbrainz_token`, `listenbrainz_user`, `youtube_api_key`.
- Unit tests via `httpx.MockTransport` (no new deps).

### S2 — History import + ID resolution ✓ (synthetic tests; real run once export lands)
- `etl/history.py` — export JSON → `plays` table (ts, ms_played, skipped, spotify_id, artist, track, album).
- `etl/resolve.py` — distinct (artist, title, spotify_id) → `track_xref(spotify_id, mbid, isrc, deezer_id, match_score, source)`; resumable, 1 req/s.
- Drop dead `rag_chunks` table.
- Make: `make import-history`, `make resolve-ids`.

### S3 — Recommendations (open-world discovery)
- Existing `recommend/engine.py` stays: closed-world recs over the 2,182-track corpus.
- New `recommend/discover.py`: candidates from Last.fm similar + LB Radio + LB CF + Deezer related; dedupe on (artist, title) casefold.
- S3a ✓ `recommend/discover.py`: heuristic score = source agreement + mean match + artist-level support − log1p(plays) penalty; ≤2 per artist; known/new-artist mix. Verified live (LB Radio + Deezer; Last.fm 403 → key not active).
- S3b (data-gated): learned reranker — label = played ≥30s & not skipped from `plays`; LightGBM on source/match/genre features. Retrain once export is loaded.

### S4 — Playback (Chainlit)
- Also fixed: `etl/db.get_connection` deleted a *valid* DB on any IOException (header check looked for DUCK at offset 0; it is at 8) — a lock held by the MCP server would wipe it. Committed DB is already empty → `make init-db`.
- S4 design: `local_playlists` + `local_playlist_tracks` + `playable_cache(track_key, youtube_video_id)` DDL; `resolve_playable(video_id=, search_youtube=)`; `library/playlists.py` (save/list/get, `to_jspf`); `library/playback.py` (cached playable — YouTube search is 100 quota units); agent tools `discover_tracks`, `play_track`; app renders `cl.Audio` + YouTube link from this turn's tool outputs, Play/Save-playlist actions, JSPF as `cl.File`.
- `cl.Audio` for Deezer preview; YouTube embed/link for full track. Playlists saved locally (DuckDB) + exportable as JSPF (ListenBrainz-importable).
- S4 ✓ (2026-10-29): `library/{playlists,playback}.py`; `agent/tools/discover.py` — `discover_tracks`, `play_track` (content_and_artifact), `save_playlist` (HITL, writes `data/playlists/<id>.jspf`), `list_playlists`; `format_response` surfaces `tracks`/`playable` artifacts; Chainlit ▶ actions (top 5), 💾 save (AskUserMessage → `cl.File` JSPF), inline 30s audio. 582 unit tests pass; live smoke OK.
- Found: LB Radio match is positional (1 − i/n) vs Last.fm absolute similarity → LB dominates ranking. Normalise per source (rank-based) in S3b. `plays` empty until export imported.

### S5 — Agent / MCP swap
- Replace `agent/tools/spotify_read.py`, `spotify_write.py` and Spotify MCP tools with sources-backed tools.
- Delete `src/spotify/`, Spotify settings, `.spotify_cache` gotchas; update CLAUDE.md + `.env.example`.
- S5 ✓ (2026-10-29): `agent/tools/music.py` (history from local `plays`; MusicBrainz/Last.fm/Deezer lookups), `recommend_*` take names (lookup → legacy corpus IDs; engine gets `playlist_tracks_fn` instead of a Spotify client). 21 agent tools. MCP server re-exposes agent tools (19; no memory, `save_playlist` without interrupt). `etl/sync.py` slimmed to Last.fm genres + genre profiles. `user_id` setting (alias `SPOTIFY_USER_ID` keeps memory namespace). Deleted `src/spotify/`, Spotify tools/tests, `notebooks/08_sync.ipynb`, `make auth`. 554 tests pass.
- Left for user: strip `SPOTIFY_*` from `.env.example` / `.env` (agent can't touch env files); README still describes Spotify.

### S6 — Offline / downloads (legal sources only)
Catalogs do **not** overlap — each covers a different slice:
| Source | Catalog | Access | Plan |
|---|---|---|---|
| Jamendo | ~600k CC-licensed indie tracks | free API (client_id), MP3 download URLs | `sources/jamendo.py` — search + download into library |
| Internet Archive | Live Music Archive (taper-friendly bands), netlabels, public domain | free API, no key | `sources/archive_org.py` — search + download |
| Free Music Archive | CC indie | no stable public API | link-out only |
| Bandcamp | huge indie + many mainstream artists, buy DRM-free | no public API | link-out (search URL) for purchase |
| Freegal / Hoopla | major-label (Sony) via library card, weekly quota | no public API | manual; files land in library folder |
- Downloads → `data/library/` (gitignored), tagged with MBID; `library` table in DuckDB.
- Serve with **Navidrome** (docker, Subsonic API) → phone apps (Symfonium/Substreamer) cache offline.
- Agent: `play` prefers local file > YouTube > Deezer preview.
- No yt-dlp / YouTube or Deezer downloading (ToS).

### S7 — Evals
- Update tool-trajectory evals for new tool names (`golden_intent.jsonl` still has `get_spotify_recommendations`, `get_listening_history`).

### Env
- `lightgbm` can't load `libomp.dylib` → whole unit suite (and pre-commit hook) fails at `tests/conftest.py`. Fix: `brew install libomp`.

### User actions (blocking S2/S3 real runs)
1. Spotify → Account → Privacy → request **Extended streaming history** (takes days–weeks). Drop JSON in `data/listening_history/`.
2. ListenBrainz account → copy user token → `LISTENBRAINZ_TOKEN`, `LISTENBRAINZ_USER`. Import the Spotify export there too.
3. ~~Last.fm key~~ ✓ verified live 2026-10-29.
4. ~~`YOUTUBE_API_KEY`~~ ✓ set, verified live 2026-10-28. LB token ✓.
5. S6: Jamendo client_id (devportal.jamendo.com).
