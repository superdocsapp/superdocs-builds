"""Credential loading. Reads .env (gitignored) into the process only.

Never logs, prints, or serialises a value. Callers ask for a key by name and
get it back or get an empty string; anything that reports on credentials
reports presence, never content.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"


def load_env(path: Path | None = None) -> None:
    """Load .env into os.environ without overwriting existing values."""
    path = path or ENV_PATH
    if not path.exists():
        return
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


def get(name: str) -> str:
    load_env()
    return os.environ.get(name, "")


def present(name: str) -> bool:
    """True if the credential is available. Used for reporting; leaks nothing."""
    return bool(get(name))
