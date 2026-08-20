"""Configuration-driven settings.

Every tunable lives here so no module hardcodes behaviour. Settings are read
once and injected (see :func:`get_settings`) rather than imported ad-hoc, which
keeps modules testable with overridden configuration.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "SuperDocs Agentic Document Intelligence"
    environment: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://superdocs:superdocs@localhost:5432/superdocs"

    # --- LLM ---------------------------------------------------------------
    gemini_api_key: str | None = None
    llm_model: str = "gemini-2.5-flash"
    embedding_model: str = "text-embedding-004"
    embedding_dim: int = 768
    llm_max_retries: int = 3
    llm_timeout_s: float = 60.0

    # Deterministic mode: skips every paid API call. Used by CI and as the
    # graceful-degradation path when no key is configured.
    offline_mode: bool = False

    # --- Storage -----------------------------------------------------------
    storage_dir: Path = Path("./.storage")
    watch_dir: Path = Path("./.inbox")
    max_upload_mb: int = 50
    allowed_extensions: tuple[str, ...] = (".pdf", ".docx", ".txt", ".md")

    # --- Workflow ----------------------------------------------------------
    node_max_retries: int = 3
    node_backoff_s: float = 1.5
    max_concurrent_runs: int = 8

    # --- Cost model (USD per 1M tokens), configuration not code ------------
    price_input_per_mtok: float = 0.30
    price_output_per_mtok: float = 2.50
    price_embedding_per_mtok: float = 0.15

    # Confidence below which a finding is always routed to human review.
    review_confidence_threshold: float = 0.85
    # Absolute tolerance for float comparisons in the arithmetic engine.
    arithmetic_tolerance: float = 0.01

    api_keys: list[str] = Field(default_factory=list)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key) and not self.offline_mode


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    settings.watch_dir.mkdir(parents=True, exist_ok=True)
    return settings
