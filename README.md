# listen-wiseer

Intelligent Spotify music recommendation system powered by a LangGraph agent, Anthropic Claude (Haiku), similarity models, and Wikipedia RAG. Talks to Spotify via an MCP server. Chat interface built with Chainlit.

## Architecture

```
┌─────────────────────────────────────┐
│         Chainlit Chat UI            │
└─────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────┐
│       LangGraph Agent               │
│  intent → analysis → action         │
└─────────────────────────────────────┘
          ↓                  ↓
┌──────────────────┐  ┌──────────────────┐
│  Recommend Core  │  │  Spotify Actions  │
│  (Polars)        │  │  (write ops)      │
│  • similarity    │  │  • create playlist│
│  • clustering    │  │  • add tracks     │
│  • genre (ENOA)  │  └──────────────────┘
└──────────────────┘
          ↓
┌─────────────────────────────────────┐
│  Data Layer — DuckDB + Polars       │
│  tracks · audio features · genres   │
│  playlists · faves · embeddings     │
└─────────────────────────────────────┘
          ↓                  ↓
┌──────────────────┐  ┌──────────────────┐
│   Spotify API    │  │  Wikipedia RAG   │
│   MCP Server     │  │  (Chroma +       │
│   (read ops)     │  │  sentence-       │
│                  │  │  transformers)   │
└──────────────────┘  └──────────────────┘
```

## Stack

| Layer | Tech |
|---|---|
| LLM | Anthropic Claude Haiku (`claude-haiku-4-5-20251001`) |
| Agent orchestration | LangGraph |
| Chat UI | Chainlit |
| MCP server | FastMCP |
| Data / analytics | DuckDB + Polars |
| Genre taxonomy | ENOA (6k+ genre spatial map) |
| Embeddings | sentence-transformers (local) |
| Vector store | ChromaDB |
| Config | pydantic-settings |
| Logging | structlog |

## Project Structure

```
listen-wiseer/
├── src/
│   ├── app/              # Chainlit entry point
│   ├── agent/            # LangGraph workflow (graph, nodes, state)
│   ├── mcp_server/       # FastMCP server + tools
│   ├── recommend/        # ML layer (GMM + LightGBM, Polars-native)
│   │   └── modules/      # similarity, clustering, classifiers, genre
│   ├── etl/              # DuckDB bootstrap/sync, genre tables
│   ├── spotify/          # OAuth, httpx client, fetch/write ops
│   └── utils/            # config, schemas, logging, constants
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
| `playlist_tracks` | ~2900 | Track ↔ playlist junction |
| `track_artists` | ~2900 | Track ↔ artist junction |
| `faves` | ~1500 | Personal track scores |
| `genre_map` | 291 | Custom genre taxonomy (→ gen_4/6/8) |
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
