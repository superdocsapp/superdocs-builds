"""Environment settings. Values are read when a provider call is made."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ[key] = value


def _load_env_files() -> None:
    cwd = Path.cwd()
    _load_env_file(cwd / ".env")
    _load_env_file((cwd / "../../../.env").resolve())


_load_env_files()


@dataclass(frozen=True)
class Settings:
    port: int
    glm_api_key: str
    glm_base_url: str
    glm_model: str
    glm_timeout_ms: int
    superdocs_api_key: str
    superdocs_base_url: str
    superdocs_timeout_ms: int


def get_settings() -> Settings:
    return Settings(
        port=int(os.getenv("PORT", "8000")),
        glm_api_key=os.getenv("GLM_API_KEY", ""),
        glm_base_url=os.getenv("GLM_BASE_URL", "https://api.z.ai/api/paas/v4").rstrip("/"),
        glm_model=os.getenv("GLM_MODEL", "glm-5.3"),
        glm_timeout_ms=int(os.getenv("GLM_TIMEOUT_MS", "120000")),
        superdocs_api_key=os.getenv("SUPERDOCS_API_KEY", ""),
        superdocs_base_url=os.getenv("SUPERDOCS_BASE_URL", "https://api.superdocs.app").rstrip("/"),
        superdocs_timeout_ms=int(os.getenv("SUPERDOCS_TIMEOUT_MS", "300000")),
    )
