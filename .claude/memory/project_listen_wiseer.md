---
name: listen-wiseer architecture and phase status
description: listen-wiseer project — phase status, key design decisions, corpus facts, and open questions
type: project
---

Spotify music recommendation agent. LangGraph + Chainlit + FastMCP + LightGBM + ChromaDB.

**Why:** Personal music assistant personalised to the user's own ENOA taste map — not a generic Spotify wrapper.

**Phase status (as of 2026-04-04):**
- Phase 1 ✓ — structlog, Pydantic v2, Polars loader
- Phase 1.5 ✓ — Spotify OAuth (httpx), exception hierarchy
- Phase 2 ✓ — GMM + LightGBM recommendation layer; 4 pipelines; 8 MCP tools; 222 tests passing
  - Step 11 incomplete: `make train` interrupted — only 2/~32 classifiers. First action of Phase 3 Step 1.
- Phase 3 Step 0 — ETL hardening 0a–0i ✓ DONE. **0j (feature engineering) next** — blocked on Last.fm key activation.
- Phase 3 Steps 1–5: Not started
- Phase 4 — RAG (Wikipedia + Tavily + ChromaDB). Separate plan after Phase 3 review.

**ETL / data facts (post-bootstrap as of 2026-04-04):**
- `data/listen_wiseer.db`: 2182 tracks, 291 genre mappings, 2182 enriched profiles
- `artists` table has `artist_name` column (added 2026-04-04) — populated from playlist CSVs; 1456 names
- `audio_features.features_source` — `'spotify'` for all 2182 bootstrap rows; `'lastfm'` stub for Last.fm-derived rows (numeric fields NULL until feature engineering fills them from ENOA coords)
- `genre_xy` table: 6291 ENOA genres with top/left/color — used for Last.fm tag matching (broader than curated 291-row `genre_map`)
- 229 tracks with NULL `first_genre` — `sync_lastfm_genres` fills these once Last.fm key activates
- Last.fm: `LAST_FM_API_KEY` + `LAST_FM_ID` in `.env`. Key pending manual activation by Last.fm (error 10). No OAuth needed — just wait.
- Cron: `~/Library/LaunchAgents/com.wiseer.listen-wiseer-sync.plist` registered, daily 02:00, logs to `logs/sync.log`
- Spotify audio-features endpoint confirmed dead (403 all apps, 2025) — Last.fm tags → ENOA coords are the replacement path

**Key architectural decisions:**
- 595k-row corpus. Brute-force cosine ~200ms — acceptable; FAISS deferred.
- ENOA (top/left) coordinates are the differentiator: encode user's own curation patterns, not just audio similarity.
- StructuredTool wrapping (direct Python calls) over langchain-mcp-adapters — simpler, no process management.
- Single `"artist_info"` ChromaDB collection with artist metadata filter (not per-artist collections).
- Lazy ChromaDB ingestion: fetch Wikipedia/Tavily on first query, upsert, cache.
- `MemorySaver` for in-session multi-turn only — cross-session persistence out of scope Phase 3.

**How to apply:** Next session: check Last.fm activation → run `--lastfm-limit 50` → proceed with 0j feature engineering → then `make train` → Phase 3 Steps 1–5.
