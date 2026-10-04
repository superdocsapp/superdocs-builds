"""Application configuration loaded from environment variables."""
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """All configuration is loaded from environment variables or .env file.
    Secrets are NEVER hardcoded in source."""

    # Database
    database_url: str = Field(
        default="postgresql+psycopg://postgres:password@localhost:5432/superdocs",
        description="PostgreSQL connection string (uses psycopg v3 driver)",
    )

    # Dropbox
    dropbox_app_key: str = Field(default="", description="Dropbox app key")
    dropbox_app_secret: str = Field(default="", description="Dropbox app secret")
    dropbox_access_token: str = Field(default="", description="Dropbox access token")
    dropbox_webhook_secret: str = Field(default="", description="Dropbox webhook HMAC secret")

    # SuperDocs
    superdocs_api_key: str = Field(default="", description="SuperDocs API key")
    superdocs_base_url: str = Field(
        default="https://api.superdocs.app",
        description="SuperDocs API base URL",
    )

    # Worker
    default_debounce_seconds: int = Field(default=30, description="Default debounce window for file stability")
    worker_lease_timeout_minutes: int = Field(default=10, description="Minutes before a stale worker lease expires")
    max_retries: int = Field(default=3, description="Max retries for transient failures")

    # System
    system_enabled: bool = Field(default=True, description="Global kill switch for the watcher/worker")
    log_level: str = Field(default="INFO", description="Logging level")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
