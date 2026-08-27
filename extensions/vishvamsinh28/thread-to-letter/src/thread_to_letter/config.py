"""Settings. Environment first, ``.env`` as a fallback, never a key on screen."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str | os.PathLike[str] = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str

    @property
    def is_live(self) -> bool:
        return "api.superdocs.app" in self.base_url

    def redacted(self) -> str:
        if not self.api_key:
            return "<unset>"
        return f"{self.api_key[:6]}…{self.api_key[-2:]}"


def load_settings(env_file: str = ".env") -> Settings:
    load_dotenv(env_file)
    return Settings(
        api_key=os.environ.get("SUPERDOCS_API_KEY", ""),
        base_url=os.environ.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app"),
    )
