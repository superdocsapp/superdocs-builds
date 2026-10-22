from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_API_KEYS = {"your-key-here", "", "changeme", "superdocs-api-key"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    superdocs_api_key: str = "your-key-here"
    superdocs_base_url: str = "https://api.superdocs.app"

    # When True, SuperDocs is the primary intelligence layer (PII detection,
    # privilege analysis, redaction proposals via the async chat API with
    # approval_mode="ask_every_time"). The local PyMuPDF/regex/OCR path is
    # then a strictly labeled fallback used only when SuperDocs is
    # unavailable. Set to False to force fallback mode explicitly.
    superdocs_primary: bool = True

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bates_packet"

    storage_root: Path = Path("./storage")
    originals_dir: str = "originals"
    processed_dir: str = "processed"
    working_dir: str = "working"
    final_dir: str = "final"

    tesseract_cmd: str = "tesseract"
    tesseract_lang: str = "eng"

    bates_prefix: str = "CASE-"
    bates_start_number: int = 1
    bates_padding: int = 6

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False
    log_level: str = "INFO"

    @property
    def originals_path(self) -> Path:
        return self.storage_root / self.originals_dir

    @property
    def processed_path(self) -> Path:
        return self.storage_root / self.processed_dir

    @property
    def working_path(self) -> Path:
        return self.storage_root / self.working_dir

    @property
    def final_path(self) -> Path:
        return self.storage_root / self.final_dir

    @property
    def has_real_superdocs_key(self) -> bool:
        """True only when a real SuperDocs API key is configured. Placeholder
        keys (e.g. 'your-key-here' from .env.example) are never sent upstream."""
        return self.superdocs_api_key not in PLACEHOLDER_API_KEYS

    @property
    def superdocs_available(self) -> bool:
        """SuperDocs is the primary intelligence layer only when enabled AND a
        real key is configured. Otherwise the local fallback path is used and
        every proposal is explicitly labeled `local_fallback`."""
        return self.superdocs_primary and self.has_real_superdocs_key

    def ensure_directories(self) -> None:
        for path in [
            self.originals_path,
            self.processed_path,
            self.working_path,
            self.final_path,
        ]:
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
