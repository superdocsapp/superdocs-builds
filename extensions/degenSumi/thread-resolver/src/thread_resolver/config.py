"""Configuration read from the environment.

Credentials are never accepted as arguments, written to disk, or logged. Values
are read once at startup and validated, so a missing key fails immediately with
a message naming the fix rather than at the first network call.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class JudgeProvider(StrEnum):
    NONE = "none"
    """No language judgement. Threads with several participants go to a person."""

    GEMINI = "gemini"
    """Gemini, on the free tier. The only provider with an adapter."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    superdocs_api_key: SecretStr = Field(default=SecretStr(""))
    """Wrapped so that printing or logging the settings object cannot leak it."""

    superdocs_base_url: str = "https://api.superdocs.app"

    judge_provider: JudgeProvider = JudgeProvider.NONE
    judge_api_key: SecretStr = Field(default=SecretStr(""))
    judge_model: str = ""

    request_timeout_seconds: float = 30.0
    """Per-request ceiling. Long edit jobs are polled rather than held open."""

    job_poll_seconds: float = 2.0
    job_timeout_seconds: float = 600.0
    """Edits on large documents can run for minutes before a result appears."""

    @property
    def has_superdocs_key(self) -> bool:
        return bool(self.superdocs_api_key.get_secret_value().strip())

    @property
    def has_judge(self) -> bool:
        return self.judge_provider is not JudgeProvider.NONE and bool(
            self.judge_api_key.get_secret_value().strip()
        )

    def require_superdocs_key(self) -> str:
        """The SuperDocs key, or an error naming where to get one."""
        key = self.superdocs_api_key.get_secret_value().strip()
        if not key:
            raise MissingCredential(
                "SUPERDOCS_API_KEY is not set. Copy .env.example to .env and add a key "
                "created at use.superdocs.app under Settings > API Keys."
            )
        return key


class MissingCredential(Exception):
    """Raised when an operation needs a credential that was never supplied."""
