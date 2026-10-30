from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Memory namespace; SPOTIFY_USER_ID still accepted so existing memories stay reachable
    user_id: str = Field(
        default="default", validation_alias=AliasChoices("USER_ID", "SPOTIFY_USER_ID")
    )

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # Embeddings (local sentence-transformers)
    embedding_model: str = "all-MiniLM-L6-v2"

    # App
    log_level: str = "INFO"
    web_dist_dir: str = ""  # built web/ the API serves at /; empty = web/dist (dev: Vite serves)

    # MCP server (host/port only apply to streamable-http)
    mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    mcp_server_port: int = 8765
    mcp_server_host: str = "localhost"

    # Data paths
    listening_history_path: str = "./data/listening_history"
    track_features_cache: str = "./data/cache/track_features.parquet"
    genre_metadata_cache: str = "./data/cache/genre_metadata.parquet"

    # Last.fm
    last_fm_api_key: str = ""

    # Free music sources (MusicBrainz, ListenBrainz, Deezer, YouTube)
    source_user_agent: str = "listen-wiseer/0.1 (https://github.com/ramseywise/listen-wiseer)"
    listenbrainz_token: str = ""
    listenbrainz_user: str = ""
    youtube_api_key: str = ""
    jamendo_client_id: str = ""  # legal CC downloads (S6)

    # Navidrome (Subsonic API) — the player app's library server; creds stay server-side
    navidrome_url: str = "http://localhost:4533"
    navidrome_user: str = ""
    navidrome_password: str = ""
    music_dir: str = ""  # library root Navidrome serves; empty = data/library (absolute if set)

    # Web search (artist/genre context)
    tavily_api_key: str = ""

    # Agent
    max_agent_iterations: int = 10
    agent_timeout_seconds: int = 60
    max_history_messages: int = 20

    # Intent routing
    intent_confidence_threshold: float = 0.4
    max_tool_validation_retries: int = 1

    # Verification loop (maker/checker)
    max_verification_retries: int = 2  # checker retry cap, independent of ReAct loop cap
    verification_score_threshold: float = 0.5  # minimum score to pass; below → retry
    stall_detection_threshold: int = 3  # identical consecutive tool sequences → escalate

    # Memory / persistence (priority: postgres > redis > in-memory)
    postgres_url: str = ""
    redis_url: str = ""
    redis_ttl_minutes: int = 1440
    memory_store_url: str | None = None  # Postgres URL for persistent cross-session memory

    # LangFuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    enable_langfuse: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
