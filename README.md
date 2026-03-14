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
│  Analysis Core   │  │  Spotify Actions  │
│  (Polars)        │  │  (spotipy write)  │
│  • similarity    │  │  • create playlist│
│  • clustering    │  │  • add tracks     │
│  • genre         │  └──────────────────┘
└──────────────────┘
          ↓
┌─────────────────────────────────────┐
│  Data Layer (Polars + Pydantic)     │
│  listening history · track features │
│  genre metadata · vectorstore       │
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
| Data processing | Polars |
| Embeddings | sentence-transformers (local, no API key) |
| Vector store | ChromaDB |
| Spotify client | spotipy (OAuth with token caching) |
| Config | pydantic-settings |
| Observability | structlog + OpenTelemetry (Jaeger via OTLP, optional) |

## Project Structure

```
listen-wiseer/
├── src/
│   ├── app/
│   │   └── main.py              # Chainlit entry point
│   ├── agent/
│   │   ├── graph.py             # LangGraph workflow
│   │   ├── nodes.py             # Agent nodes
│   │   └── state.py             # State schema
│   ├── mcp_server/
│   │   ├── server.py            # FastMCP server
│   │   └── tools.py             # Tool definitions
│   ├── data/
│   │   ├── loader.py            # Polars data loading
│   │   └── schemas.py           # Pydantic schemas
│   ├── analysis/
│   │   ├── core.py              # Pure analysis functions
│   │   ├── similarity.py        # Cosine / euclidean / hybrid
│   │   └── clustering.py        # Spectral clustering
│   ├── actions/
│   │   └── spotify_actions.py   # Spotify write operations
│   ├── rag/
│   │   ├── wiki_rag.py          # Wikipedia RAG
│   │   └── embeddings.py        # Embedding wrapper
│   ├── observability/
│   │   ├── logging.py           # structlog setup
│   │   └── tracing.py           # OpenTelemetry (optional)
│   └── utils/
│       └── const.py             # Audio feature constants, playlist IDs
├── data/
│   ├── listening_history/       # Spotify history JSON exports
│   ├── cache/                   # Parquet feature cache
│   └── vectorstore/             # ChromaDB
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── setup.sh
└── Makefile
```

## Quickstart

```bash
# 1. Run setup (installs uv, creates .env, installs deps, creates data dirs)
./setup.sh

# 2. Fill in credentials in .env
#    SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET — developer.spotify.com/dashboard
#    SPOTIFY_USER_ID   — your Spotify username
#    ANTHROPIC_API_KEY — console.anthropic.com

# 3. Place Spotify listening history exports in data/listening_history/

# 4. Run the chat app (opens browser, prompts Spotify OAuth on first run)
make app

# 5. Or run with Docker
make infra-up
```

## Development

```bash
make app          # Run Chainlit UI
make mcp-server   # Run MCP server in terminal
make infra-up     # Start Docker services
make infra-down   # Stop and remove volumes
make infra-logs   # Follow container logs
make lint         # Ruff + black check
make format       # Ruff + black fix
make test         # pytest
```

### Optional services (Docker profiles)

```bash
# Enable Jaeger tracing UI (localhost:16686)
docker compose --profile observability up -d

# Enable PostgreSQL
docker compose --profile database up -d
```

## Spotify Scopes

The app requests the following Spotify permissions on first login:

- `playlist-read-private` / `playlist-read-collaborative`
- `playlist-modify-private` / `playlist-modify-public`
- `user-library-read`
- `user-read-recently-played`
- `user-top-read`

Token is cached in `.spotify_cache` (gitignored).
