# listen-wiseer

A personal music copilot — LangGraph agent with Claude, ML recommendation models, and agentic web search for music context. Chat interface via Chainlit; the agent discovers music through free open sources (MusicBrainz, ListenBrainz, Last.fm, Deezer), plays it for free (YouTube + Deezer previews), and calls local ML tools directly. No Spotify account required.

## The Product

This project started in **2023** as a recommendation engine. Spotify's algorithmic playlists didn't match my taste, so I built my own — GMM clustering, LightGBM reranking, and a custom genre taxonomy (ENOA) to capture how I actually think about music: mixing sounds across Brazilian, Japanese, West African, Arabic, and bossa nova traditions based on sonic similarity rather than rigid genre labels.

Since then, Spotify's own recommendations have honestly improved. But the core model is still useful — candidates now come from open similarity sources (ListenBrainz, Last.fm, Deezer), then **LightGBM boosting** filters which tracks fit my taste and which playlist to slot them into.

An interesting constraint shift: before 2024, Spotify provided an **Audio Features API** (danceability, energy, valence, etc.) that fed directly into the model. They've since restricted that endpoint, so the model now relies on **derived proxies** — ENOA genre embeddings, playlist co-occurrence patterns, and the personalized cross-genre connections I curate (e.g., links across the African diaspora, or between Arabic music and bossa nova).

In **2026** the project left Spotify entirely: Premium cancelled, and the developer API closed to personal apps. Everything now runs on free, open sources — MusicBrainz for canonical identity, ListenBrainz / Last.fm / Deezer for similarity, YouTube and Deezer for playback. The Spotify years live on as an archive: the old library tables and the privacy-export listening history.

## The Learning Platform

With agentic AI, this repo evolved from a static model into a **music copilot** — a LangGraph agent that reads my listening history, discovers new music around it, reasons over it with web search context, and saves playlists. It's as much a tool for self-learning as it is for the product itself.

The recent focus areas:

- **Agentic tooling** — open-source discovery + free playback, recommendation engine, Tavily web search, and long-term taste memory all wired as LangGraph tools with intent routing to the right chain
- **Eval harness** — three-tier eval: deterministic intent/route (Tier 1, CI-safe), live trajectory against the compiled graph (Tier 2), RAGAS faithfulness + tool correctness (Tier 3)
- **Persistent agent memory** — taste profile storage via langmem so the agent accumulates preference knowledge across sessions
- **Agentic web search** — artist/genre queries are decomposed and fanned out across parallel Tavily calls when complex, synthesized with citations, and confidence-gated so the agent admits when it can't find grounded info instead of guessing

## Architecture

```
┌──────────────────────────────────────────────────────┐
│            Chainlit Chat UI  :8501                   │
└──────────────────────────────────────────────────────┘
                         │
┌──────────────────────────────────────────────────────┐
│                 LangGraph Agent                      │
│                                                      │
│  classify_intent → clarify_or_proceed                │
│       → rewrite_query → agent_node                   │
│       → validate_tool_output → format_response       │
│                                                      │
│  Checkpointer: Postgres (Docker) / MemorySaver (dev) │
│  Memory: langmem procedural optimizer                │
└──────────────────────────────────────────────────────┘
        │           │           │            │
┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌──────────────┐
│ Music    │ │ Recommend│ │ Agentic Web  │ │    Memory    │
│ Tools    │ │ Engine   │ │ Search       │ │    Tools     │
│          │ │          │ │              │ │              │
│ discover │ │ by_track │ │ decompose →  │ │ taste_memory │
│ play     │ │ by_genre │ │ Tavily fan-  │ │ search_taste │
│ history  │ │ clusters │ │ out → synth  │ │              │
│ playlists│ │ (Polars) │ │ + confidence │ │              │
└──────────┘ └──────────┘ └──────────────┘ └──────────────┘
        │           │                         │
┌──────────────────────────────────────────────────────┐
│         Data Layer — DuckDB + Polars                 │
│  plays · tracks · genres · playlists · faves         │
│  local_playlists · ENOA embeddings                   │
└──────────────────────────────────────────────────────┘
        │                         │
┌──────────────────┐     ┌──────────────────┐
│ MusicBrainz      │     │  MCP Server      │
│ ListenBrainz     │     │  :8765           │
│ Last.fm · Deezer │     │  (agent tools    │
│ YouTube (links)  │     │   for Claude     │
│                  │     │   Desktop/Code)  │
└──────────────────┘     └──────────────────┘
```

## Stack

| Layer | Tech |
|---|---|
| LLM | Anthropic Claude Haiku (`claude-haiku-4-5-20251001`) |
| Agent orchestration | LangGraph (intent routing, persistent memory via langmem) |
| Chat UI | Chainlit |
| MCP server | FastMCP (re-exposes the agent's music tools) |
| Music data | MusicBrainz · ListenBrainz · Last.fm · Deezer (free APIs) |
| Playback | YouTube links + Deezer 30s previews (no downloads from either) |
| Web search | Tavily — agentic: query decompose/fan-out, multi-source synthesis, confidence gating |
| Data / analytics | DuckDB + Polars |
| ML models | GMM clustering + LightGBM reranker (scikit-learn pipelines) |
| Genre taxonomy | ENOA (6k+ genre spatial map) |
| Checkpointer | Postgres (Docker) / MemorySaver (local dev) |
| Eval harness | 3-tier: intent/route → trajectory → RAGAS faithfulness |
| ETL | Spotify privacy export → `plays`; MBID resolution; Last.fm genre tags → DuckDB |
| Config | pydantic-settings |
| Logging | structlog |

## Project Structure

```
listen-wiseer/
├── src/
│   ├── app/              # Chainlit entry point
│   ├── agent/            # LangGraph workflow
│   │   ├── graph.py            # compiled state graph + routing
│   │   ├── graph_nodes.py      # node functions (intent, rewrite, agent)
│   │   ├── validation.py       # post-tool-output validation + confidence gate
│   │   ├── response.py         # final response formatting + citations
│   │   ├── intent.py           # keyword intent classifier, decompose/complexity
│   │   ├── state.py            # AgentState schema
│   │   ├── dependencies.py     # checkpointer factory (Postgres / MemorySaver)
│   │   ├── memory_store.py     # procedural prompt management
│   │   ├── memory_helpers.py   # episodic recall/store, memory stats
│   │   └── tools/        # domain tool modules
│   │       ├── discover.py       # discover_tracks, play_track, save/list playlists
│   │       ├── music.py          # history (local plays), artist lookups
│   │       ├── recommend.py      # by_track, by_artist, by_genre, by_playlist (names)
│   │       ├── memory.py         # manage/search taste memory
│   │       └── web_search.py     # agentic Tavily search (decompose/fan-out/synthesize)
│   ├── mcp_server/       # FastMCP server — agent tools over MCP
│   ├── recommend/        # ML layer (GMM + LightGBM, Polars-native)
│   │   └── modules/      # similarity, clustering, classifiers, genre (ENOA)
│   ├── etl/              # DuckDB bootstrap, history import, ID resolution, Last.fm genres
│   ├── sources/          # httpx clients: MusicBrainz, ListenBrainz, Last.fm, Deezer, YouTube, Jamendo, Internet Archive
│   ├── library/          # local playlists (JSPF export), playback resolution, legal downloads
│   └── utils/            # config, schemas, logging, constants
├── evals/                # Evaluation harness
│   ├── agent/            # trajectory eval, intent eval, graders, cost gate
│   ├── graders/          # answer quality graders
│   ├── tasks/            # golden set, synthetic generation, models
│   ├── metrics/          # retrieval scoring
│   └── datasets/         # golden_intent.jsonl (50 hand-crafted samples)
├── infrastructure/
│   └── containers/       # docker-compose.yml (postgres, db-init, mcp, app)
├── data/
│   ├── archived/              # source CSVs (gitignored)
│   └── spotify_train_data.csv # external training corpus (gitignored, ~200MB)
├── models/               # trained artifacts (gitignored)
├── notebooks/            # exploration (gitignored)
├── pyproject.toml
├── Makefile
└── setup.sh
```

## Quickstart

### Docker (recommended)

```bash
# 1. Copy and fill credentials
cp .env.example .env
# Required: ANTHROPIC_API_KEY, TAVILY_API_KEY, LAST_FM_API_KEY, YOUTUBE_API_KEY
# Optional: LISTENBRAINZ_TOKEN, LISTENBRAINZ_USER, JAMENDO_CLIENT_ID, USER_ID, LANGFUSE_*

# 2. Build + start the full stack
make infra-build
make infra-up

# 3. Smoke-test the running stack
make infra-smoke

# 4. Open the chat
open http://localhost:8501
```

The `db-init` container bootstraps the DuckDB schema and trains models on first run. Subsequent starts skip training if `models/` is already populated.

### Local dev

```bash
# 1. Install deps
uv sync

# 2. Copy and fill credentials
cp .env.example .env

# 3. Import listening history (Spotify privacy export JSON → data/listening_history/)
make import-history
make resolve-ids        # match plays to MusicBrainz/Deezer IDs (resumable)

# 4. Train recommendation models
make train

# 5. Run the chat app
make app
```

### Fresh machine / full rebuild

Only needed if you want to rebuild DuckDB from archived CSVs:

```bash
make init-db                                       # bootstrap from archived CSVs
PYTHONPATH=src uv run python -m etl.genre_tables   # populate genre profile tables
make train
```

## Development

```bash
# Local dev
make app              # Chainlit UI (localhost:8501)
make mcp-server       # MCP server for Claude Desktop / Code (localhost:8765)
make import-history   # Spotify privacy export → plays
make resolve-ids      # plays → MusicBrainz/Deezer IDs
make data-sync        # Last.fm genre tags → genre profiles
make navidrome        # Serve data/library/ to Subsonic apps (localhost:4533)
make train            # Fit GMM + LightGBM → models/*.pkl
make train-cat        # Train with CatBoost instead
make train-compare    # Head-to-head comparison (no models saved)

# Docker stack
make infra-up         # Start full stack (postgres, db-init, mcp, app)
make infra-down       # Teardown + remove volumes
make infra-build      # Rebuild images
make infra-ps         # Container status
make infra-logs       # Follow logs
make infra-smoke      # Smoke-test: postgres + app health

# Eval harness
make eval-ci          # CI gate: heuristic graders vs baseline (no API cost, <30s)
make eval-full        # All tiers: trajectory + RAGAS (costs money, needs ANTHROPIC_API_KEY)
make eval-unit        # Tier 1 — intent/route (free, CI-safe)
make eval-trajectory  # Tier 2 — live graph trajectory (costs money)
make eval-e2e         # Tier 3 — RAGAS faithfulness + tool correctness

# Eval tiers
# Tier 1 (CI gate): deterministic intent/route eval against golden dataset.
#   Runs on every PR via .github/workflows/eval.yml. No API key. Fails PR if any
#   metric drops >5% from evals/datasets/eval_baseline.json.
# Tier 2 (manual): live trajectory eval against compiled LangGraph graph. Costs money.
# Tier 3 (manual): RAGAS faithfulness + tool-correctness graders. Costs money.
#   Run locally with `make eval-full` or `make eval-e2e`. Never auto-triggered in CI.

# Code quality
make lint             # ruff check + format check
make format           # ruff fix + format
make test             # full pytest suite
make test-unit        # unit tests with coverage
make test-fast        # unit tests, no coverage
```

## Database

`infrastructure/db/listen_wiseer.db` is a DuckDB file committed to the repo (~7MB). Run `make init-db` to rebuild it from the archived CSVs and `make import-history` to load listening history.

| Table | Description |
|---|---|
| `plays` | Listening history from the Spotify privacy export |
| `track_ids` | Cross-source identity (MusicBrainz MBID canonical, Deezer ID) |
| `local_playlists` / `local_playlist_tracks` | Playlists saved by the agent (stored by artist/title/MBID) |
| `playable_cache` | Cached YouTube video lookups |
| `library` | Legally downloaded files in `data/library/` (source, licence, MBID) |
| `tracks` | Core track metadata, archived from Spotify (~2200 rows) |
| `artists` | Artist metadata (~1700 rows) |
| `playlists` | Archived Spotify playlists (~80 rows) |
| `playlist_tracks` | Track-playlist junction (~2900 rows) |
| `faves` | Personal track scores (~1500 rows) |
| `genre_map` | Custom genre taxonomy gen_4/6/8 (291 rows) |
| `genre_xy` | ENOA genre spatial coordinates (6291 rows) |
| `track_profile` | VIEW — denormalized join for agent/models |

## Architectural Choices

**DuckDB** — local analytics and Polars interop. Also supports vector similarity search, so it doubles as both the analytical engine and vector store.

**Polars over pandas** — lazy evaluation for large joins, eager for small transforms. All ML feature engineering runs through Polars before converting to numpy arrays for scikit-learn.

**structlog** — structured logging everywhere. Dot-separated event names (`train.gmm.fit`, `sync.playlists`) with bound fields for counts, IDs, and metrics.

**MCP + direct tools** — the MCP server re-exposes the agent's own tools (minus memory) so other clients get the same behaviour. The LangGraph agent calls Python functions directly via `bind_tools` — no subprocess overhead.

**Eval-first for agentic features** — with many possible tool orchestrations, it's hard to know if changes improve things without a feedback loop. Three-tier eval gives signal before shipping agent changes.

**Tavily over a doc-RAG pipeline** — a Wikipedia → sentence-transformers → DuckDB vector-search pipeline (`rag_core/`, inherited from an earlier, unrelated support-bot project and never fully adapted to music) required a pre-populated corpus and went stale. It was deleted rather than kept "for later" — the one piece that was music-domain and load-bearing (keyword intent classification) moved to `agent/intent.py`. Tavily returns grounded, fresh answers in ~1s with zero local state; **agentic web search** (query decomposition, parallel fan-out, confidence-gated synthesis with citations) replaces what a doc-RAG pipeline would otherwise be needed for, without maintaining a corpus.

**Free sources over a single platform** — no one free API covers everything, so each does what it is best at: MusicBrainz is the identity spine (MBIDs), Last.fm / ListenBrainz / Deezer supply similarity, YouTube and Deezer handle playback. Tracks are stored by artist/title/MBID rather than any platform's ID, and playlists export as JSPF so they can move to ListenBrainz or anywhere else.

## Playback & downloads

Playback is free and link-based: the full track on YouTube, plus a Deezer link and a 30-second preview inline in the chat. Nothing is downloaded from YouTube or Deezer (their terms forbid it). Offline listening uses legally downloadable catalogues only — Jamendo (Creative Commons; set `JAMENDO_CLIENT_ID`) and the Internet Archive (no key). Ask the agent to download a track and it lands in `data/library/`; `make navidrome` serves that folder over the Subsonic API (http://localhost:4533) so phone apps like Symfonium can cache it offline.

## Acknowledgments

Thanks to **Prasson Shukla** and **Ramon Garate** from [Cord](https://cord.com) — a sandbox-based platform for parallelized tasks from OpenCode and Claude Code — for help building out the agentic layer on top of the ML foundation.
