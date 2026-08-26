from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file so the service finds it regardless
# of the working directory uvicorn was launched from.
_ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    superdocs_api_key: str = ""
    superdocs_base_url: str = "https://api.superdocs.app"

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
