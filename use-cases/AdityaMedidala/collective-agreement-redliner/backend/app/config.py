from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    superdocs_api_key: str = ""
    superdocs_base_url: str = "https://api.superdocs.app"

    database_url: str = "sqlite:///./redliner.db"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
