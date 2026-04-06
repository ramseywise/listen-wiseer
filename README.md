# listen-wiseer

A Spotify copilot — LangGraph agent with Claude, ML recommendation models, and a music-domain RAG pipeline. Chat interface via Chainlit; the agent calls Spotify, Wikipedia, and local ML tools directly.

## The Product

This project started in **2023** as a recommendation engine. Spotify's algorithmic playlists didn't match my taste, so I built my own — GMM clustering, LightGBM reranking, and a custom genre taxonomy (ENOA) to capture how I actually think about music: mixing sounds across Brazilian, Japanese, West African, Arabic, and bossa nova traditions based on sonic similarity rather than rigid genre labels.

Since then, Spotify's own recommendations have honestly improved. But the core model is still useful — I use Spotify's collaborative recommendations as candidates, then apply **LightGBM boosting** to filter which tracks fit my taste and which playlist to slot them into.

An interesting constraint shift: before 2024, Spotify provided an **Audio Features API** (danceability, energy, valence, etc.) that fed directly into the model. They've since restricted that endpoint, so the model now relies on **derived proxies** — ENOA genre embeddings, playlist co-occurrence patterns, and the personalized cross-genre connections I curate (e.g., links across the African diaspora, or between Arabic music and bossa nova). There's a lot of research in the ENOA genre taxonomy around dimensionality reduction for spatial genre mapping. I'm curious what the agent will eventually surface about these connections.

## The Learning Platform

With agentic AI, this repo evolved from a static model into a **Spotify copilot** — a LangGraph agent that fetches my listening data, reasons over it with RAG context, and creates playlists. It's as much a tool for self-learning as it is for the product itself (very much a WIP).

The recent focus areas:

- **RAG for music context** — Spotify provides basic artist metadata, but I'm using Wikipedia to pull in richer context about music history, cultural lineage, and genre evolution. This feeds into both search and recommendation.
- **Eval harness** — custom graders, synthetic task generation, and local trial runners to measure how well the agentic tools actually perform. Understanding evaluation for these systems is a key interest.
- **Persistent agent memory** — taste profile storage via langmem so the agent accumulates preference knowledge across sessions.
- **Intent routing + query understanding** — the agent classifies user intent and routes to the right tool chain (recommend, search, RAG lookup, playlist action).

## Architectural Choices

**DuckDB** — chose it early for local analytics and Polars interop. Turned out to be a great call: DuckDB now supports vector similarity search, so it doubles as both the analytical engine and vector store. One database, two jobs.

**Polars over pandas** — lazy evaluation for large joins, eager for small transforms. All ML feature engineering runs through Polars before converting to numpy arrays for scikit-learn.

**structlog** — structured logging everywhere instead of stdlib logging or print. Dot-separated event names (`train.gmm.fit`, `sync.playlists`) with bound fields for counts, IDs, and metrics. Makes debugging agent tool chains much easier.

**MCP + direct tools** — the MCP server exposes Spotify read operations for external tool use, but the LangGraph agent calls Python functions directly (recommend, search, RAG, memory) via `bind_tools` — no subprocess overhead.

**Eval-first for agentic features** — with so many possible tool orchestrations, it's hard to know if changes improve things. The eval harness (graders + synthetic tasks + trials) gives a feedback loop before shipping agent changes.

## Acknowledgments

A big thank you to **Prasson Shukla** and **Ramon Garate** from [Cord](https://cord.com) — a sandbox-based platform for parallelized tasks from OpenCode and Claude Code. With their help I was able to vibe-code much of the agentic layer, building on top of the ML foundation I'd already contributed. Definitely check it out!

## Architecture

```
┌─────────────────────────────────────┐
│         Chainlit Chat UI            │
└─────────────────────────────────────┘
                   |
┌─────────────────────────────────────┐
│       LangGraph Agent               │
│  intent routing → query             │
│  understanding → tool dispatch      │
│  (persistent memory + langmem)      │
└─────────────────────────────────────┘
       |              |             |
┌────────────┐ ┌────────────┐ ┌────────────────┐
│ Recommend  │ │  Spotify   │ │   RAG Core     │
│ Engine     │ │  Client    │ │  (Wikipedia →  │
│ (Polars)   │ │  (httpx)   │ │   DuckDB)      │
│ • similar  │ │ • search   │ │ • query under- │
│ • cluster  │ │ • playlist │ │   standing     │
│ • genre    │ │ • history  │ │ • retrieval    │
│ • boost    │ │ • related  │ │ • generation   │
└────────────┘ └────────────┘ └────────────────┘
       |                             |
┌─────────────────────────────────────┐
│  Data Layer — DuckDB + Polars       │
│  tracks · genres · playlists ·      │
│  faves · embeddings · vectors       │
└─────────────────────────────────────┘
       |              |             |
┌────────────┐ ┌────────────┐ ┌────────────┐
│ Spotify API│ │ Wikipedia  │ │   Eval     │
│ MCP Server │ │ (chunked + │ │  Harness   │
│ (read ops) │ │  embedded) │ │ (graders + │
│            │ │            │ │  trials)   │
└────────────┘ └────────────┘ └────────────┘
```

## Stack

| Layer | Tech |
|---|---|
| LLM | Anthropic Claude Haiku (`claude-haiku-4-5-20251001`) |
| Agent orchestration | LangGraph (intent routing, persistent memory via langmem) |
| Chat UI | Chainlit |
| MCP server | FastMCP (Spotify read tools) |
| Data / analytics | DuckDB + Polars |
| ML models | GMM clustering + LightGBM reranker (scikit-learn pipelines) |
| Genre taxonomy | ENOA (6k+ genre spatial map) |
| RAG | Wikipedia → sentence-transformers → DuckDB vector search |
| Eval harness | Custom graders, synthetic task generation, local trials |
| ETL | Spotify API + Last.fm API → DuckDB sync |
| Config | pydantic-settings |
| Logging | structlog |

## Project Structure

```
listen-wiseer/
├── src/
│   ├── app/              # Chainlit entry point
│   ├── agent/            # LangGraph workflow (graph, nodes, state, memory, optimizer)
│   ├── mcp_server/       # FastMCP server — Spotify read tools
│   ├── recommend/        # ML layer (GMM + LightGBM, Polars-native)
│   │   └── modules/      # similarity, clustering, classifiers, genre (ENOA)
│   ├── rag_core/         # Music-domain RAG pipeline
│   │   ├── preprocessing/  # Wikipedia fetching, chunking, parsing
│   │   ├── retrieval/      # DuckDB vector search, embedding, reranking
│   │   ├── generation/     # LLM-based answer generation
│   │   ├── orchestration/  # Query understanding, intent routing, RAG graph
│   │   └── schemas/        # Pydantic models for RAG domain
│   ├── etl/              # DuckDB bootstrap, Spotify + Last.fm sync
│   ├── spotify/          # OAuth, httpx client, fetch/write ops
│   └── utils/            # config, schemas, logging, constants
├── evals/                # Evaluation harness
│   ├── graders/          # Answer quality graders
│   ├── tasks/            # Golden set extraction, synthetic generation
│   ├── trials/           # Eval trial runners
│   └── metrics/          # Scoring metrics
├── infrastructure/
│   ├── db/
│   │   └── listen_wiseer.db   # DuckDB — committed (~7MB, no training data)
│   └── containers/            # Docker compose + app/mcp images
├── data/
│   ├── archived/              # Source CSVs (gitignored)
│   └── spotify_train_data.csv # External training corpus (gitignored, ~200MB)
├── models/               # Trained artifacts — joblib (gitignored)
├── notebooks/            # Exploration only (gitignored)
├── pyproject.toml
├── Makefile
└── setup.sh
```

## Database

`infrastructure/db/listen_wiseer.db` is a DuckDB file committed to the repo (~7MB).

### Tables

| Table | Rows | Description |
|-------|------|-------------|
| `tracks` | ~2200 | Core track metadata |
| `audio_features` | ~2200 | Spotify audio features |
| `track_genre` | ~2200 | Genre assignments (manual/lookup/model) |
| `artists` | ~1700 | Artist metadata |
| `artist_genre` | ~1500 | Derived artist genre profiles |
| `playlists` | ~80 | Your Spotify playlists |
| `playlist_genre` | ~30 | Derived playlist genre profiles |
| `playlist_tracks` | ~2900 | Track-playlist junction |
| `track_artists` | ~2900 | Track-artist junction |
| `faves` | ~1500 | Personal track scores |
| `genre_map` | 291 | Custom genre taxonomy (gen_4/6/8) |
| `genre_xy` | 6291 | ENOA genre spatial coordinates |
| `track_profile` | VIEW | Denormalized join for agent/models |

**External training corpus** (`data/spotify_train_data.csv`, ~595k rows) is gitignored — load separately for model training via `etl.genre_tables`.

## Quickstart

```bash
# 1. Install deps
uv sync

# 2. Copy and fill credentials
cp .env.example .env
# SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET — developer.spotify.com/dashboard
# SPOTIFY_USER_ID   — your Spotify username
# ANTHROPIC_API_KEY — console.anthropic.com
# LAST_FM_API_KEY   — last.fm/api

# 3. DB is already committed — pull and go
#    To sync fresh data from Spotify + Last.fm:
make data-sync

# 4. Run the chat app
make app
```

### Fresh machine / full rebuild

Only needed if you want to rebuild the DB from scratch:

```bash
make init-db                                       # bootstrap from archived CSVs
make data-sync                                     # pull from Spotify + Last.fm
PYTHONPATH=src uv run python -m etl.genre_tables   # populate genre profile tables
```

## Development

```bash
make app          # Run Chainlit UI
make mcp-server   # Run MCP server
make data-sync    # Incremental Spotify + Last.fm sync
make init-db      # Bootstrap DB from archived CSVs
make lint         # ruff check
make format       # ruff fix
make test         # pytest tests/unit/
```

## Spotify Scopes

- `playlist-read-private` / `playlist-read-collaborative`
- `playlist-modify-private` / `playlist-modify-public`
- `user-library-read`
- `user-read-recently-played`
- `user-top-read`

Token cached in `.spotify_cache` (gitignored).
