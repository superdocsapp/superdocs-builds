"""Runtime configuration.

Reads `.env` from the classroom-app/ root. Anchored, not relative: a
relative ".env" resolves against the process's cwd, which differs by entry
point (Makefile targets `cd backend` first; a manually-launched uvicorn
might not) — same bug zoom-app hit and fixed the same way.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# core -> app -> backend -> classroom-app: four levels up from this file.
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    # Google OAuth — Google Cloud Console -> Credentials -> OAuth 2.0 Client ID
    # (Application type: Web application).
    google_client_id: str = ""
    google_client_secret: str = ""
    # Must match the Authorized redirect URI registered with Google exactly.
    google_redirect_uri: str = "http://localhost:8020/api/auth/callback"

    # SuperDocs — docs.superdocs.app account -> POST /v1/users/me/api-keys.
    superdocs_api_key: str = ""
    superdocs_base_url: str = "https://api.superdocs.app"

    # Starlette SessionMiddleware signing secret. Generate with
    # `python -c "import secrets; print(secrets.token_hex(32))"`.
    session_secret: str = ""

    public_base_url: str = "http://localhost:8020"
    log_level: str = "INFO"

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def superdocs_configured(self) -> bool:
        return bool(self.superdocs_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
