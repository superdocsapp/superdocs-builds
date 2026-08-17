"""Settings from .env.

Deliberately tiny: this build has no database and no server, so a settings
framework would be more machinery than the problem needs.

The editor is chosen here rather than at every call site, which is what lets the
whole test suite run on the mock without a key.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from ro_normalizer.superdocs.editor import DocumentEditor, MockDocumentEditor

ROOT = Path(__file__).resolve().parents[2]


def load_env(path: Path | None = None) -> dict[str, str]:
    """Read .env without adding a dependency. Real environment variables win."""
    values: dict[str, str] = {}
    env_file = path or ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    values.update({k: v for k, v in os.environ.items() if k in values or k.startswith("SUPERDOCS_")})
    return values


@lru_cache
def settings() -> dict[str, str]:
    return load_env()


def get(name: str, default: str = "") -> str:
    return settings().get(name, os.environ.get(name, default))


def build_editor(backend: str | None = None) -> DocumentEditor:
    """`mock` unless explicitly told otherwise.

    Defaulting to the real API would mean a stray run spending operations.
    """
    chosen = (backend or get("EDITOR_BACKEND", "mock")).lower()

    if chosen == "mock":
        return MockDocumentEditor()

    if chosen == "superdocs":
        from ro_normalizer.superdocs.client import SuperDocsDocumentEditor

        return SuperDocsDocumentEditor(
            api_key=get("SUPERDOCS_API_KEY"),
            base_url=get("SUPERDOCS_BASE_URL") or "https://api.superdocs.app",
            timeout=float(get("SUPERDOCS_TIMEOUT_SECONDS", "300")),
        )

    raise ValueError(
        f"EDITOR_BACKEND='{chosen}' is not a known editor. Use 'mock' or 'superdocs'."
    )
