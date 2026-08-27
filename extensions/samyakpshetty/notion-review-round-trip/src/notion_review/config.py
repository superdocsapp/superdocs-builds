"""Typed, env-driven configuration.

Config is loaded from a mapping (``os.environ`` by default) rather than read from globals,
so tests construct a config explicitly and never depend on the ambient environment. Secrets
live only here and in the client that uses them — never in logs (see ``logging.py``).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ProviderMode = Literal["fake", "live"]
LogFormat = Literal["json", "console"]
HandoffMode = Literal["notion", "folder"]


class ConfigError(ValueError):
    """Raised when configuration is missing or inconsistent for the chosen mode."""


class Config(BaseModel):
    """Runtime configuration for the review round-trip.

    The whole test suite and ``make demo`` run with ``provider="fake"`` and no keys. The
    ``live`` provider is what talks to real SuperDocs and Notion; it requires credentials,
    validated lazily by :meth:`require_live` so a ``fake`` run never needs them.
    """

    model_config = {"frozen": True}

    provider: ProviderMode = "fake"

    # SuperDocs
    superdocs_api_key: str | None = None
    superdocs_base_url: str = "https://api.superdocs.app"

    # Notion
    notion_token: str | None = None
    notion_page_id: str | None = None
    notion_version: str = "2022-06-28"  # Notion's required API-version header
    # The Notion database a team adds a row to when they want a page sent for review. Optional:
    # without it the service only takes in returned files and `send` is the entry point.
    notion_requests_database_id: str = ""
    # How the document reaches reviewers and comes back. ``notion`` keeps the whole handoff on
    # the request row, so nobody leaves Notion; ``folder`` uses a watched directory, which is a
    # real channel when it is a synced shared drive. The round-trip does not care which: the
    # file carries its own round id and is matched however it returns.
    handoff: HandoffMode = "notion"

    # Durable substrate. None -> the zero-infra SQLite store (used by the keyless suite).
    database_url: str | None = None

    # Observability
    log_format: LogFormat = "json"

    # --- Cost / budget controls (first-class; SuperDocs is the only metered call) ---
    # One SuperDocs operation covers up to this many edited sections, so we batch changes
    # into groups of this size to spend the fewest ops possible.
    sections_per_op: int = Field(default=25, ge=1)
    # Hard ceiling on ops a single review round may spend before the stopping rule trips.
    max_ops_per_round: int = Field(default=200, ge=1)
    # In sample mode we propose at most this many changes — learn cost on a slice first.
    sample_size: int | None = Field(default=None, ge=1)
    # Safety rail: a single edit's text may not exceed this many characters. Untrusted markup (or a
    # hostile comment steering the AI) could otherwise balloon a block; over-cap edits are refused.
    max_edit_chars: int = Field(default=20_000, ge=1)

    # --- Resilience knobs ---
    superdocs_max_retries: int = Field(default=5, ge=0)
    # Re-submit a chat whose job comes back failed with a transient "engine at capacity" error —
    # the error itself says to re-submit. Bounded; then the round degrades gracefully.
    superdocs_chat_retries: int = Field(default=3, ge=0)
    superdocs_backoff_base_s: float = Field(default=0.5, gt=0)
    superdocs_poll_timeout_s: float = Field(default=600.0, gt=0)
    superdocs_poll_interval_s: float = Field(default=2.0, gt=0)
    notion_max_retries: int = Field(default=5, ge=0)
    notion_min_interval_s: float = Field(default=0.34, ge=0)  # ~3 req/s Notion rate limit

    @model_validator(mode="after")
    def _check_sample(self) -> Config:
        if self.sample_size is not None and self.sample_size < 1:
            raise ConfigError("sample_size must be >= 1 when set")
        return self

    def require_live(self) -> Config:
        """Assert the credentials needed for the live provider; return self for chaining."""
        if self.provider != "live":
            return self
        missing = [
            name
            for name, value in (
                ("SUPERDOCS_API_KEY", self.superdocs_api_key),
                ("NOTION_TOKEN", self.notion_token),
            )
            if not value
        ]
        if missing:
            raise ConfigError(
                f"provider=live requires {', '.join(missing)}; set them in .env "
                "(see .env.example) or use provider=fake"
            )
        return self

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Config:
        env = os.environ if environ is None else environ

        def _int(key: str, default: int) -> int:
            raw = env.get(key)
            return int(raw) if raw else default

        provider = env.get("PROVIDER", "fake").strip().lower()
        if provider not in ("fake", "live"):
            raise ConfigError(f"PROVIDER must be 'fake' or 'live', got {provider!r}")

        log_format = env.get("LOG_FORMAT", "json").strip().lower()
        if log_format not in ("json", "console"):
            raise ConfigError(f"LOG_FORMAT must be 'json' or 'console', got {log_format!r}")

        handoff = env.get("HANDOFF", "notion").strip().lower()
        if handoff not in ("notion", "folder"):
            raise ConfigError(f"HANDOFF must be 'notion' or 'folder', got {handoff!r}")

        sample_raw = env.get("SAMPLE_SIZE")
        return cls(
            provider=provider,
            superdocs_api_key=env.get("SUPERDOCS_API_KEY") or None,
            superdocs_base_url=env.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app"),
            notion_token=env.get("NOTION_TOKEN") or None,
            notion_page_id=env.get("NOTION_PAGE_ID") or None,
            notion_version=env.get("NOTION_VERSION", "2022-06-28"),
            notion_requests_database_id=env.get("NOTION_REQUESTS_DB", ""),
            handoff=handoff,
            database_url=env.get("DATABASE_URL") or None,
            log_format=log_format,
            sections_per_op=_int("SECTIONS_PER_OP", 25),
            max_ops_per_round=_int("MAX_OPS_PER_ROUND", 200),
            sample_size=int(sample_raw) if sample_raw else None,
        )
