"""Load SuperDocs settings from the environment. The API key is never printed."""

from __future__ import annotations

import os
from collections.abc import Mapping

from job_architecture.superdocs.errors import ConfigurationError
from job_architecture.superdocs.models import SuperDocsSettings

DEFAULT_BASE_URL = "https://api.superdocs.app"
DEFAULT_TIMEOUT_SECONDS = 120.0


def load_settings(
    *,
    environ: Mapping[str, str] | None = None,
    require_api_key: bool = True,
) -> SuperDocsSettings:
    env = environ if environ is not None else os.environ
    api_key = (env.get("SUPERDOCS_API_KEY") or "").strip()
    if require_api_key and not api_key:
        raise ConfigurationError(
            "SUPERDOCS_API_KEY is missing. Set it in the server environment "
            "(see .env.example). Never put the key in frontend code or fixtures."
        )
    base_url = (env.get("SUPERDOCS_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
    timeout_raw = env.get("REQUEST_TIMEOUT_SECONDS") or str(DEFAULT_TIMEOUT_SECONDS)
    try:
        timeout = float(timeout_raw)
    except ValueError as exc:
        raise ConfigurationError("REQUEST_TIMEOUT_SECONDS must be a number") from exc
    if timeout <= 0:
        raise ConfigurationError("REQUEST_TIMEOUT_SECONDS must be positive")
    return SuperDocsSettings(api_key=api_key, base_url=base_url, timeout_seconds=timeout)
