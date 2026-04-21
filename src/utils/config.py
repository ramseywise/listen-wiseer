from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Spotify
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = "http://127.0.0.1:8000/callback"
    spotify_user_id: str = ""
    spotify_cache_path: str = ".spotify_cache"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # Embeddings (local sentence-transformers)
    embedding_model: str = "all-MiniLM-L6-v2"

    # App
    log_level: str = "INFO"
    enable_tracing: bool = False
    jaeger_endpoint: str = "http://localhost:14268/api/traces"

    # MCP server
    mcp_server_port: int = 8765
    mcp_server_host: str = "localhost"

    # Data paths
    listening_history_path: str = "./data/listening_history"
    track_features_cache: str = "./data/cache/track_features.parquet"
    genre_metadata_cache: str = "./data/cache/genre_metadata.parquet"

    # Similarity
    similarity_method: str = "hybrid"
    audio_feature_weight: float = 0.6
    genre_weight: float = 0.4

    # Last.fm
    last_fm_api_key: str = ""
    last_fm_id: str = ""

    # Web search (artist/genre context)
    tavily_api_key: str = ""

    # Agent
    max_agent_iterations: int = 10
    agent_timeout_seconds: int = 60
    max_history_messages: int = 20

    # Intent routing
    intent_confidence_threshold: float = 0.4
    max_tool_validation_retries: int = 1

    # Memory / persistence (priority: postgres > redis > in-memory)
    postgres_url: str = ""
    redis_url: str = ""
    redis_ttl_minutes: int = 1440

    # LangFuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    enable_langfuse: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
