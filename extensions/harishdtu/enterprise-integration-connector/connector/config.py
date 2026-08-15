"""
Configuration. The API key comes from the environment (SUPERDOCS_API_KEY) or is
passed explicitly by the host platform's credential vault at runtime — never
hardcoded, never logged. Most enterprise integration platforms inject connection
credentials into the connector at invocation time rather than via process env;
`ConnectorConfig.from_platform_credential()` is the seam for that (see README's
"Adapting to a specific platform" section).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://api.superdocs.app"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 4
# Job-status polling cadence (distinct from the HTTP retry backoff in
# http_client.py, which handles transient request failures). This is the
# steady-state "check again" loop, e.g. behavior #13 in the brief: configurable
# initial delay, max delay, backoff factor, and timeout, with jitter.
DEFAULT_POLL_INITIAL_INTERVAL_SECONDS = 2.0
DEFAULT_POLL_MAX_INTERVAL_SECONDS = 30.0
DEFAULT_POLL_BACKOFF_FACTOR = 1.5
DEFAULT_POLL_JITTER_RATIO = 0.2  # +/- 20% jitter applied to each computed delay
# SuperDocs jobs are purged ~1 hour after creation (per docs.superdocs.app/guides/async-jobs).
# The worker must stop polling well before that and surface a typed timeout rather
# than poll a job that has already been garbage-collected server-side.
DEFAULT_MAX_POLL_SECONDS = 55 * 60
# Bounded retry for delivering the platform callback (distinct from SuperDocs
# API retries) -- a callback URL being briefly unreachable must never be
# confused with, or allowed to overwrite, a SuperDocs job's own outcome.
DEFAULT_CALLBACK_MAX_ATTEMPTS = 5
DEFAULT_CALLBACK_INITIAL_INTERVAL_SECONDS = 1.0
DEFAULT_CALLBACK_MAX_INTERVAL_SECONDS = 60.0
DEFAULT_CALLBACK_BACKOFF_FACTOR = 2.0


@dataclass(frozen=True)
class ConnectorConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    poll_initial_interval_seconds: float = DEFAULT_POLL_INITIAL_INTERVAL_SECONDS
    poll_max_interval_seconds: float = DEFAULT_POLL_MAX_INTERVAL_SECONDS
    poll_backoff_factor: float = DEFAULT_POLL_BACKOFF_FACTOR
    poll_jitter_ratio: float = DEFAULT_POLL_JITTER_RATIO
    max_poll_seconds: int = DEFAULT_MAX_POLL_SECONDS
    callback_max_attempts: int = DEFAULT_CALLBACK_MAX_ATTEMPTS
    callback_initial_interval_seconds: float = DEFAULT_CALLBACK_INITIAL_INTERVAL_SECONDS
    callback_max_interval_seconds: float = DEFAULT_CALLBACK_MAX_INTERVAL_SECONDS
    callback_backoff_factor: float = DEFAULT_CALLBACK_BACKOFF_FACTOR

    def __post_init__(self):
        if not self.api_key:
            raise ValueError(
                "ConnectorConfig requires a non-empty api_key. Never hardcode it — "
                "read from SUPERDOCS_API_KEY or the host platform's credential vault."
            )
        if not (self.api_key.startswith("sk_") or self.api_key.startswith("lce_")):
            raise ValueError(
                "api_key does not look like a SuperDocs key (expected sk_... or lce_... prefix). "
                "Refusing to proceed rather than send a malformed Authorization header."
            )

    def redacted(self) -> str:
        """Safe-to-log representation. Never call str(config) or log config.api_key directly."""
        tail = self.api_key[-4:] if len(self.api_key) >= 4 else "****"
        return f"ConnectorConfig(api_key=***{tail}, base_url={self.base_url!r})"

    @classmethod
    def from_env(cls, **overrides) -> ConnectorConfig:
        """Standard path for local dev / self-hosted workers: SUPERDOCS_API_KEY env var."""
        api_key = os.environ.get("SUPERDOCS_API_KEY", "")
        return cls(api_key=api_key, **overrides)

    @classmethod
    def from_platform_credential(cls, credential: str, **overrides) -> ConnectorConfig:
        """
        Seam for platform-native credential injection. Workato/Tray/Boomi/MuleSoft
        connector SDKs each have their own secret-injection mechanism (a "connection"
        object, an input schema field marked as a password type, etc.) rather than
        process environment variables. Whatever the platform hands the connector at
        runtime, pass it here — this method exists so that adaptation point is a
        single, obvious line rather than scattered `os.environ` calls.
        """
        return cls(api_key=credential, **overrides)

    def __repr__(self) -> str:  # never let a stray print(config) leak the key
        return self.redacted()
