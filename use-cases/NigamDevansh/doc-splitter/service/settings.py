"""One typed boundary for configuration.

Its own file, not the analyst's: this app is a `cp -r` into another repo and
cannot inherit a configuration system it does not carry.

See use-cases/doc-splitter/README.md § "Standalone".
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", frozen=True
    )

    superdocs_api_key: str = ""
    """Absent, the tool still parses a document and shows the split it *would*
    make, with the coverage proof — it just cannot export, and says so."""
    superdocs_base_url: str = "https://api.superdocs.app"
    sd_timeout_s: float = 120.0

    data_dir: Path = ROOT / "data"
    max_parts: int = 10
    """A guard, not a target. Each part costs one export op, so a mis-click on
    forty headings should not spend forty ops."""
    verify_coverage: bool = True
    """Refuse to export parts that don't reconstruct the master. Off only for
    debugging; `/health` says when it is off."""

    @property
    def database_path(self) -> Path:
        return self.data_dir / "db" / "splitter.db"

    def missing_requirements(self) -> list[str]:
        missing: list[str] = []
        if not self.superdocs_api_key:
            missing.append(
                "SUPERDOCS_API_KEY — parts cannot be exported. Uploading, marking "
                "split points and checking coverage all still work."
            )
        if not self.verify_coverage:
            missing.append(
                "VERIFY_COVERAGE is off — parts are exported without checking that "
                "they reconstruct the master."
            )
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
