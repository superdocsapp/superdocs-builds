from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = Field(min_length=1)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    mcp_allowed_hosts: list[str] = Field(
        default_factory=lambda: [
            "127.0.0.1",
            "127.0.0.1:*",
            "localhost",
            "localhost:*",
            "[::1]",
            "[::1]:*",
        ]
    )
    mcp_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1",
            "http://127.0.0.1:*",
            "http://localhost",
            "http://localhost:*",
            "http://[::1]",
            "http://[::1]:*",
        ]
    )
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    superdocs_api_key: SecretStr | None = None
    superdocs_api_base: str = "https://api.superdocs.app/v1"
    superdocs_http_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    superdocs_worker_poll_seconds: float = Field(
        default=2.0,
        gt=0,
        le=60,
        validation_alias="phase3_worker_poll_seconds",
    )
    watch_worker_claim_limit: int = Field(default=10, ge=1, le=100)
    watch_scan_lease_seconds: int = Field(default=300, ge=30, le=3600)
    watch_max_items_per_scan: int = Field(default=5000, ge=1, le=100_000)
    docrelay_artifact_dir: Path = Path(".docrelay-artifacts")
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str | None = None
    oauth_token_encryption_keys: SecretStr | None = None
    oauth_token_encryption_primary_version: str = "v1"
    google_oauth_state_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    google_access_token_refresh_skew_seconds: int = Field(default=60, ge=0, le=600)
    google_http_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    google_baseline_max_attempts: int = Field(default=3, ge=1, le=5)
    docrelay_owner_subject: str = Field(default="local-development-owner", min_length=1)

    @model_validator(mode="after")
    def validate_database_driver(self) -> Self:
        if not self.database_url.startswith("postgresql+asyncpg://") and not (
            self.app_env == "test" and self.database_url.startswith("sqlite+aiosqlite://")
        ):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg (SQLite is test-only)")

        oauth_values = (
            self.google_oauth_client_id,
            self.google_oauth_client_secret,
            self.google_oauth_redirect_uri,
            self.oauth_token_encryption_keys,
        )
        configured_count = sum(value is not None for value in oauth_values)
        if configured_count not in {0, len(oauth_values)}:
            raise ValueError(
                "Google OAuth configuration is incomplete; client ID, client secret, "
                "redirect URI, and encryption keyring must be configured together"
            )
        if (
            self.app_env == "production"
            and self.docrelay_owner_subject == "local-development-owner"
        ):
            raise ValueError("DOCRELAY_OWNER_SUBJECT must be explicit in production")
        if self.app_env == "production" and not self.superdocs_api_base.startswith("https://"):
            raise ValueError("SUPERDOCS_API_BASE must use HTTPS in production")
        return self

    @property
    def google_oauth_configured(self) -> bool:
        return all(
            value is not None
            for value in (
                self.google_oauth_client_id,
                self.google_oauth_client_secret,
                self.google_oauth_redirect_uri,
                self.oauth_token_encryption_keys,
            )
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # BaseSettings loads database_url from env
