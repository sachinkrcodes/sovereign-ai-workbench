"""Central configuration. Every value can be overridden with an environment variable
(or a .env file), so the same code runs on a laptop, in Docker and on AWS."""

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Sovereign AI Workbench"
    app_version: str = "0.4.0"
    environment: str = "development"

    # SQLite for quick local runs; Postgres (pgvector) in Docker / AWS.
    database_url: str = "sqlite:///./data/app.db"

    # Local disk now. Stage 6 swaps this for Amazon S3 without touching the routers.
    storage_dir: Path = Path("./data/uploads")
    max_upload_mb: int = 25

    # Chunking (used by RAG in stage 2)
    chunk_size: int = 900
    chunk_overlap: int = 150

    # Local AI engine (Ollama). Models run on your own machine / network - nothing is sent out.
    ollama_base_url: str = "http://localhost:11434"
    embedding_model: str = "nomic-embed-text"
    # nomic-embed-text works best with these prefixes; set both to empty for other models.
    embedding_doc_prefix: str = "search_document: "
    embedding_query_prefix: str = "search_query: "
    chat_model: str = "llama3.2:3b"
    ai_timeout_seconds: int = 180
    chat_context_tokens: int = 6144
    embed_batch_size: int = 16

    # Security (stage 4)
    setup_token: str = ""  # if set, creating the very first admin requires this value
    token_ttl_hours: int = 12
    login_max_failures: int = 5
    login_window_minutes: int = 15

    # Usage governance (stage 4). Models run locally, so real cost is $0; the "equivalent"
    # prices below are ILLUSTRATIVE rates (change them) to show what a hosted API would charge.
    daily_token_limit: int = 200000  # per non-admin user per UTC day
    cloud_price_per_million_prompt: float = 0.15
    cloud_price_per_million_completion: float = 0.60

    # Comma separated list of allowed browser origins
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _check_chunking(self) -> "Settings":
        if self.chunk_size < 200:
            raise ValueError("chunk_size must be at least 200")
        if not 0 <= self.chunk_overlap < self.chunk_size // 2:
            raise ValueError("chunk_overlap must be >= 0 and less than half of chunk_size")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
