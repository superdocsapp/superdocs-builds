"""Configuration: .env loader + credential resolution (never logs secrets)."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


def resolve_api_key(explicit: str | None = None, dotenv: str | Path = ".env") -> str | None:
    load_dotenv(dotenv)
    return explicit or os.environ.get("SUPERDOCS_API_KEY") or None
