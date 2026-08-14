"""Central configuration.

Everything is read from the environment via pydantic-settings so a new tenant,
deployment, or limit is a config change, not a code change. No secret is ever
hardcoded here.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core ---
    app_env: str = "local"
    log_level: str = "INFO"

    # --- Database ---
    # Default is async Postgres. Tests override with sqlite+aiosqlite.
    database_url: str = "postgresql+asyncpg://superdocs:superdocs@localhost:5432/gateway"

    # --- Queue ---
    redis_url: str = "redis://localhost:6379/0"

    # --- SuperDocs upstream ---
    superdocs_base_url: str = "https://api.superdocs.app"
    superdocs_api_key: str = "mock-key-for-local"
    superdocs_timeout_seconds: float = 30.0

    # --- Admin ---
    admin_api_key: str = "change-me-admin-key"

    # --- Webhooks ---
    webhook_signing_secret: str = "change-me-webhook-secret"
    webhook_timeout_seconds: float = 10.0

    # --- Uploads ---
    upload_dir: str = "/data/uploads"
    upload_chunk_size: int = 1024 * 1024  # 1 MiB
    max_upload_bytes: int = 50 * 1024 * 1024  # 50 MiB

    # --- Budget guard ---
    sample_mode: bool = True
    sample_max_sections: int = Field(default=25, ge=1)


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so settings are parsed once per process."""
    return Settings()
