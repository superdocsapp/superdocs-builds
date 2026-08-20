"""Environment/config loading for the winloss_superdocs CLI.

Fails clearly (not silently) when a required credential is missing, per the
project's engineering guidelines. Never hard-codes a key.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


class MissingAPIKeyError(RuntimeError):
    """Raised when SUPERDOCS_API_KEY is required but not set."""


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    base_url: str
    max_operations: int
    small_sample_threshold: int
    request_timeout_seconds: int
    poll_interval_seconds: float
    poll_timeout_seconds: float


def load_settings() -> Settings:
    return Settings(
        api_key=os.environ.get("SUPERDOCS_API_KEY") or None,
        base_url=os.environ.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app"),
        max_operations=int(os.environ.get("WINLOSS_MAX_OPERATIONS", "20")),
        small_sample_threshold=int(os.environ.get("WINLOSS_SMALL_SAMPLE_THRESHOLD", "3")),
        request_timeout_seconds=int(os.environ.get("WINLOSS_REQUEST_TIMEOUT", "60")),
        poll_interval_seconds=float(os.environ.get("WINLOSS_POLL_INTERVAL", "2")),
        poll_timeout_seconds=float(os.environ.get("WINLOSS_POLL_TIMEOUT", "900")),
    )


def require_api_key(settings: Settings) -> str:
    """Return the API key or raise a clear, actionable error.

    Never used for --dry-run paths, which must work with zero credentials.
    """
    if not settings.api_key:
        raise MissingAPIKeyError(
            "SUPERDOCS_API_KEY is not set. Copy .env.example to .env, add a key "
            "from https://use.superdocs.app -> Settings -> API Keys, and export it "
            "(or use `--dry-run` to preview the calls this command would make "
            "without any credentials)."
        )
    return settings.api_key
