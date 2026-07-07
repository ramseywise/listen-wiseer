# listen-wiseer

A Spotify copilot — LangGraph agent with Claude, ML recommendation models, and agentic web search for music context. Chat interface via Chainlit; the agent calls Spotify, web search, and local ML tools directly.

## The Product

This project started in **2023** as a recommendation engine. Spotify's algorithmic playlists didn't match my taste, so I built my own — GMM clustering, LightGBM reranking, and a custom genre taxonomy (ENOA) to capture how I actually think about music: mixing sounds across Brazilian, Japanese, West African, Arabic, and bossa nova traditions based on sonic similarity rather than rigid genre labels.

Since then, Spotify's own recommendations have honestly improved. But the core model is still useful — I use Spotify's collaborative recommendations as candidates, then apply **LightGBM boosting** to filter which tracks fit my taste and which playlist to slot them into.

An interesting constraint shift: before 2024, Spotify provided an **Audio Features API** (danceability, energy, valence, etc.) that fed directly into the model. They've since restricted that endpoint, so the model now relies on **derived proxies** — ENOA genre embeddings, playlist co-occurrence patterns, and the personalized cross-genre connections I curate (e.g., links across the African diaspora, or between Arabic music and bossa nova).

## The Learning Platform

With agentic AI, this repo evolved from a static model into a **Spotify copilot** — a LangGraph agent that fetches my listening data, reasons over it with web search context, and creates playlists. It's as much a tool for self-learning as it is for the product itself.

The recent focus areas:

- **Agentic tooling** — Spotify read/write, recommendation engine, Tavily web search, and long-term taste memory all wired as LangGraph tools with intent routing to the right chain
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
│ Spotify  │ │ Recommend│ │ Agentic Web  │ │    Memory    │
│ Tools    │ │ Engine   │ │ Search       │ │    Tools     │
│          │ │          │ │              │ │              │
│ search   │ │ by_track │ │ decompose →  │ │ taste_memory │
│ history  │ │ by_genre │ │ Tavily fan-  │ │ search_taste │
│ playlists│ │ clusters │ │ out → synth  │ │              │
│ create   │ │ (Polars) │ │ + confidence │ │              │
└──────────┘ └──────────┘ └──────────────┘ └──────────────┘
        │           │                         │
┌──────────────────────────────────────────────────────┐
│         Data Layer — DuckDB + Polars                 │
│  tracks · genres · playlists · faves                 │
│  ENOA embeddings                                     │
└──────────────────────────────────────────────────────┘
        │                         │
┌──────────────┐         ┌──────────────────┐
│ Spotify API  │         │  MCP Server      │
│ Last.fm API  │         │  :8765           │
│ (ETL sync)   │         │  (Spotify read   │
│              │         │   tools for      │
│              │         │   Claude Desktop)│
└──────────────┘         └──────────────────┘
```

## Stack

| Layer | Tech |
|---|---|
| LLM | Anthropic Claude Haiku (`claude-haiku-4-5-20251001`) |
| Agent orchestration | LangGraph (intent routing, persistent memory via langmem) |
| Chat UI | Chainlit |
| MCP server | FastMCP (Spotify read tools for Claude Desktop) |
| Web search | Tavily — agentic: query decompose/fan-out, multi-source synthesis, confidence gating |
| Data / analytics | DuckDB + Polars |
| ML models | GMM clustering + LightGBM reranker (scikit-learn pipelines) |
| Genre taxonomy | ENOA (6k+ genre spatial map) |
| Checkpointer | Postgres (Docker) / MemorySaver (local dev) |
| Eval harness | 3-tier: intent/route → trajectory → RAGAS faithfulness |
| ETL | Spotify API + Last.fm API → DuckDB sync |
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
│   │       ├── spotify_read.py   # search, history, playlists, related
│   │       ├── spotify_write.py  # create_playlist, add_tracks
│   │       ├── recommend.py      # by_track, by_artist, by_genre
│   │       ├── memory.py         # manage/search taste memory
│   │       └── web_search.py     # agentic Tavily search (decompose/fan-out/synthesize)
│   ├── mcp_server/       # FastMCP server — Spotify read tools
│   ├── recommend/        # ML layer (GMM + LightGBM, Polars-native)
│   │   └── modules/      # similarity, clustering, classifiers, genre (ENOA)
│   ├── etl/              # DuckDB bootstrap, Spotify + Last.fm sync
│   ├── spotify/          # OAuth, httpx client, fetch/write ops
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
# Required: SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_USER_ID,
#           ANTHROPIC_API_KEY, TAVILY_API_KEY
# Optional: LAST_FM_API_KEY, LANGFUSE_*

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

# 3. Spotify auth (one-time)
make auth

# 4. Sync listening data from Spotify
make data-sync

# 5. Train recommendation models
make train

# 6. Run the chat app
make app
```

### Fresh machine / full rebuild

Only needed if you want to rebuild DuckDB from archived CSVs (no Spotify auth required):

```bash
make init-db                                       # bootstrap from archived CSVs
PYTHONPATH=src uv run python -m etl.genre_tables   # populate genre profile tables
make train
```

## Development

```bash
# Local dev
make app              # Chainlit UI (localhost:8501)
make mcp-server       # MCP server for Claude Desktop (localhost:8765)
make data-sync        # Incremental Spotify + Last.fm sync
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
make eval-unit        # Tier 1 — intent/route (free, CI-safe)
make eval-trajectory  # Tier 2 — live graph trajectory (costs money)
make eval-e2e         # Tier 3 — RAGAS faithfulness + tool correctness

# Code quality
make lint             # ruff check + format check
make format           # ruff fix + format
make test             # full pytest suite
make test-unit        # unit tests with coverage
make test-fast        # unit tests, no coverage
```

## Database

`infrastructure/db/listen_wiseer.db` is a DuckDB file committed to the repo (~7MB). Run `make init-db && make data-sync` to populate with fresh Spotify data.

| Table | Description |
|---|---|
| `tracks` | Core track metadata (~2200 rows) |
| `artists` | Artist metadata (~1700 rows) |
| `playlists` | Your Spotify playlists (~80 rows) |
| `playlist_tracks` | Track-playlist junction (~2900 rows) |
| `faves` | Personal track scores (~1500 rows) |
| `genre_map` | Custom genre taxonomy gen_4/6/8 (291 rows) |
| `genre_xy` | ENOA genre spatial coordinates (6291 rows) |
| `track_profile` | VIEW — denormalized join for agent/models |

## Architectural Choices

**DuckDB** — local analytics and Polars interop. Also supports vector similarity search, so it doubles as both the analytical engine and vector store.

**Polars over pandas** — lazy evaluation for large joins, eager for small transforms. All ML feature engineering runs through Polars before converting to numpy arrays for scikit-learn.

**structlog** — structured logging everywhere. Dot-separated event names (`train.gmm.fit`, `sync.playlists`) with bound fields for counts, IDs, and metrics.

**MCP + direct tools** — the MCP server exposes Spotify read operations for Claude Desktop. The LangGraph agent calls Python functions directly via `bind_tools` — no subprocess overhead.

**Eval-first for agentic features** — with many possible tool orchestrations, it's hard to know if changes improve things without a feedback loop. Three-tier eval gives signal before shipping agent changes.

**Tavily over a doc-RAG pipeline** — a Wikipedia → sentence-transformers → DuckDB vector-search pipeline (`rag_core/`, inherited from an earlier, unrelated support-bot project and never fully adapted to music) required a pre-populated corpus and went stale. It was deleted rather than kept "for later" — the one piece that was music-domain and load-bearing (keyword intent classification) moved to `agent/intent.py`. Tavily returns grounded, fresh answers in ~1s with zero local state; **agentic web search** (query decomposition, parallel fan-out, confidence-gated synthesis with citations) replaces what a doc-RAG pipeline would otherwise be needed for, without maintaining a corpus.

## Spotify Scopes

- `playlist-read-private` / `playlist-read-collaborative`
- `playlist-modify-private` / `playlist-modify-public`
- `user-library-read`
- `user-read-recently-played`
- `user-top-read`

Token cached in `.spotify_cache` (gitignored).

## Acknowledgments

Thanks to **Prasson Shukla** and **Ramon Garate** from [Cord](https://cord.com) — a sandbox-based platform for parallelized tasks from OpenCode and Claude Code — for help building out the agentic layer on top of the ML foundation.
