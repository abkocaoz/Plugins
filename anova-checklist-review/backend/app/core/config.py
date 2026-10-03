from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "anova-checklist-review"
    log_level: str = "INFO"
    auth_mode: str = "dev"
    dev_api_token: str = "dev-change-me"

    database_url: str = "postgresql+asyncpg://acr:change-me-acr-pg@localhost:5432/acr"
    database_url_sync: str = "postgresql+psycopg2://acr:change-me-acr-pg@localhost:5432/acr"

    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection_standards: str = "standards_bgem3_v1"
    qdrant_collection_project_docs: str = "project_documents_bgem3_v1"

    ollama_base_url: str = "http://ollama:11434"
    ollama_llm_model: str = "qwen2.5:3b"
    ollama_max_concurrency: int = 1

    embedding_url: str = "http://embedding:8080"
    embedding_model_id: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embedding_batch_size: int = 16

    upload_dir: str = "/data/uploads"
    export_dir: str = "/data/exports"

    # Background worker (extract + index). Disable in unit tests.
    worker_enabled: bool = True
    worker_poll_seconds: float = 2.0
    worker_lease_seconds: int = 120
    worker_heartbeat_seconds: int = 30
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 150


@lru_cache
def get_settings() -> Settings:
    return Settings()
