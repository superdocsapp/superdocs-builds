"""Application settings loaded from environment."""

from functools import lru_cache
from typing import Annotated, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = Field(default="Interview Preparation Brief", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    api_prefix: str = Field(default="/api/v1", alias="API_PREFIX")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    # NoDecode: allow comma-separated origins in .env (not only JSON lists)
    cors_origins: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        alias="CORS_ORIGINS",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/interview_prep",
        alias="DATABASE_URL",
    )

    # openai | anthropic | groq | gemini
    llm_provider: str = Field(default="groq", alias="LLM_PROVIDER")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1", alias="OPENAI_MODEL")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(
        default="claude-sonnet-4-20250514",
        alias="ANTHROPIC_MODEL",
    )
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.1-8b-instant", alias="GROQ_MODEL")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_MODEL")

    # openai | gemini | local  (local = free, no API key)
    embedding_provider: str = Field(default="local", alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field(
        default="local-hashing-v1",
        alias="EMBEDDING_MODEL",
    )
    embedding_dimensions: int = Field(default=1536, alias="EMBEDDING_DIMENSIONS")

    chunk_size: int = Field(default=800, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=120, alias="CHUNK_OVERLAP")
    retrieval_top_k: int = Field(default=6, alias="RETRIEVAL_TOP_K")
    evidence_fallback: str = Field(
        default="No evidence found.",
        alias="EVIDENCE_FALLBACK",
    )

    upload_dir: str = Field(default="./uploads", alias="UPLOAD_DIR")
    max_upload_mb: int = Field(default=10, alias="MAX_UPLOAD_MB")
    company_research_enabled: bool = Field(
        default=True,
        alias="COMPANY_RESEARCH_ENABLED",
    )
    http_timeout_seconds: float = Field(default=20.0, alias="HTTP_TIMEOUT_SECONDS")

    # SuperDocs cloud document API (Task 2 — build ON SuperDocs)
    superdocs_api_key: str = Field(default="", alias="SUPERDOCS_API_KEY")
    superdocs_base_url: str = Field(
        default="https://api.superdocs.app",
        alias="SUPERDOCS_BASE_URL",
    )
    superdocs_enabled: bool = Field(default=False, alias="SUPERDOCS_ENABLED")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("llm_provider", "embedding_provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("superdocs_enabled", mode="before")
    @classmethod
    def parse_bool(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return value

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() in {"development", "dev", "local"}

    @property
    def superdocs_ready(self) -> bool:
        return bool(self.superdocs_enabled and self.superdocs_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
