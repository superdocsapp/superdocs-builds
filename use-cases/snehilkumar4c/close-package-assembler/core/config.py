"""Application configuration, validated at startup.

The app refuses to boot with missing or malformed config instead of failing
mysteriously mid-run — this is the Engineering Bar's "config & secrets" item
made real, not just described. See TASK.md for the full checklist.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, HttpUrl, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration the app needs, loaded from environment / .env.

    Required fields (no default) cause Settings() to raise pydantic.ValidationError
    immediately if unset — that's the fail-fast behavior we want. Optional fields
    (SuperDocs, Langfuse) are None-able because Task 1's pipeline runs without them;
    only drafter/ and close_package/ (Task 2 / 2.2) require SuperDocs, and tracing
    is best-effort locally.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    # Required: the agent's own LLM calls run on this, not just the coding assistant.
    anthropic_api_key: SecretStr

    # Required: Task 1's own durable state (checkpoints, extracted facts, idempotency
    # keys) lives here — deliberately not dependent on SuperDocs's job store, which
    # auto-deletes jobs after 1 hour regardless of status (see TASK.md deep-dive notes).
    database_url: PostgresDsn

    # Optional at the settings level: only drafter/ and close_package/ need this.
    # Those modules should raise their own clear error if it's missing when *they*
    # need it, rather than the whole app refusing to boot for Task 1 work.
    superdocs_api_key: SecretStr | None = None
    superdocs_base_url: HttpUrl = Field(default=HttpUrl("https://api.superdocs.app"))

    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: HttpUrl = Field(default=HttpUrl("https://cloud.langfuse.com"))


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — read once, validated once, reused everywhere.

    Call this at the top of any entrypoint (FastAPI startup, a CLI, a test fixture)
    so a bad .env fails loudly and immediately, not three stages into a pipeline run.
    """
    return Settings()  # type: ignore[call-arg]  # pydantic-settings fills from env
