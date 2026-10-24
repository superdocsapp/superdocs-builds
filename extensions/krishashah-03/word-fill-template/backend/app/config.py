from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/word_ai_template_filler"

    openrouter_api_key: str = ""
    openrouter_model: str = "openrouter/free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: float = 30.0

    max_upload_size_bytes: int = 10 * 1024 * 1024

    cors_origins: list[str] = ["*"]

    @property
    def templates_dir(self) -> Path:
        return BASE_DIR / "templates"

    @property
    def uploads_dir(self) -> Path:
        return BASE_DIR / "uploads"

    @property
    def generated_dir(self) -> Path:
        return BASE_DIR / "generated"


@lru_cache
def get_settings() -> Settings:
    return Settings()
