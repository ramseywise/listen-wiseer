# SESSION.md — listen-wiseer

## Current position

- **Active plan**: `.claude/docs/PLAN.md` — Phase 3 (LangGraph Agent + Chainlit UI)
- **Phase 2 Steps 1–10**: ✓ DONE
- **Phase 2 Step 11**: Training incomplete — only 2 classifiers in `models/`. Runs as part of Phase 3 Step 1.
- **Phase 2 Step 12**: ✓ DONE
- **Phase 3 Step 0**: IN PROGRESS — 0a–0i ✓ DONE. **0j (feature engineering) is next — blocked on Last.fm key activation.**
- **Phase 3 Steps 1–5**: Not started
- **Tests**: 222 passed, 3 skipped (as of 2026-04-04)
- **Last updated**: 2026-04-04

## Token log

| Date | Start | End | Turns | Compacted? |
|------|-------|-----|-------|------------|
| 2026-04-02 | — | — | — | yes (context overflow) |
| 2026-04-03 | — | — | — | no |
| 2026-04-04 | — | — | — | yes (continued from overflow) |

## Active gotchas

- `models/` has only `gmm_corpus.pkl`, `scaler_corpus.pkl`, and 2 classifiers — training was interrupted. Step 1 of the new plan runs `make train` before anything else.
- `RecommendationEngine` raises `FileNotFoundError` at init if pkls missing. `server.py` wraps with try/except (sets `_engine = None`). `agent/tools.py` must do the same.
- `src/agent/` is currently an empty directory — no `__init__.py`. Step 2 creates the scaffold.
- `VIRTUAL_ENV` env var may be stale from a prior help-assistant session. Always use `uv run` from project root.
- ChromaDB 1.5.4: use `PersistentClient(path=...)`, not deprecated `Client()`. Relevant in Phase 4 Step 6.
- `graph.ainvoke` in Chainlit (Step 9): synchronous-heavy tools may block event loop. May need `run_in_executor`.
- `audio-features` returns 403 — **confirmed Spotify deprecation (all apps, 2025)**. Endpoint is dead for all new apps.
- `artists` table now has `artist_name VARCHAR` column (added 2026-04-04). Bootstrap populates from playlist CSVs. `sync_tracks` upserts names from `TrackFeatures.artist_names` on new tracks.
- `audio_features` now has `features_source VARCHAR DEFAULT 'spotify'`. Bootstrap explicitly inserts `'spotify'`. Last.fm path inserts `'lastfm'` stub with NULL numeric fields.
- `genre_xy` table loaded at bootstrap (6291 ENOA genres, `top`/`left`/`color`). Used by `sync_lastfm_genres` for tag matching — much broader than the curated 291-row `genre_map`.
- Last.fm API key (env: `LAST_FM_API_KEY`, `LAST_FM_ID`) — added to `.env` and `Settings`. **Key is pending Last.fm manual activation** (error 10 = key not yet approved). No OAuth flow needed; just wait for email.
- `sync_lastfm_genres` uses `artist_name` from `artists` table. 229 tracks currently have NULL `first_genre` — these will be filled once key activates.
- **Step 0j (feature engineering) is the next step** — must complete before Step 1 (`make train`). Last.fm activation is the only blocker for 0j-c; 0j-a/b/d can proceed without it.

## Open questions / blockers

- **Last.fm key activation** — pending. Check email from last.fm. Once active, run `python -m etl.sync --lastfm-limit 50` to fill first_genre for 229 tracks, then proceed with 0j.
- Phase 4 (Steps 6–8): needs `TAVILY_API_KEY` — confirm before executing.

## Next session prompt

```
We're in listen-wiseer, Phase 3 Step 0. Steps 0a–0i are DONE (222 tests passing).

**Immediate state:**
- Last.fm key (LAST_FM_API_KEY in .env) is pending activation by Last.fm — error 10.
  Once active: `PYTHONPATH=src uv run python -m etl.sync --playlists 0 --lastfm-limit 50`
  fills first_genre for 229 tracks missing it.
- genre_xy (6291 ENOA genres) is loaded in DB. artists.artist_name populated from bootstrap.
- audio_features.features_source='spotify' for all 2182 existing rows.

**Next step: 0j — Feature Engineering** (required before Step 1 / make train)
Sub-steps:
  0j-a: DB schema — add `track_embeddings` table (Track2Vec output)
  0j-b: Track2Vec embeddings via gensim (playlist co-occurrence graph, 64d) — no API key
  0j-c: Last.fm genre fill — BLOCKED until key activates (code is ready)
  0j-d: Genre-median fallback for tracks still missing features after Last.fm
  0j-e: Wire sync_lastfm_genres into daily cron (already in sync() + launchd plist registered)
  0j-f: Validate: all 2182 tracks have non-NULL features_source; track_embeddings populated

After 0j: compact → Step 1 (src/paths.py + make train).
```

_compact: 2026-04-03 00:50_
_compact: 2026-04-03 01:07_
_compact: 2026-04-03 09:13_
_compact: 2026-04-03 09:28_
_compact: 2026-04-03 09:35_
_compact: 2026-04-03 09:57_
_compact: 2026-04-03 11:26_
_compact: 2026-04-03 11:30_
_compact: 2026-04-03 22:50_
_compact: 2026-04-04 11:50_
