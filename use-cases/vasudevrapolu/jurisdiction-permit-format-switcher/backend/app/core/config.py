from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite+pysqlite:///./dev.db"
    superdocs_api_key: str | None = None
    superdocs_base_url: str = "https://api.superdocs.app"
    app_env: str = "development"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
