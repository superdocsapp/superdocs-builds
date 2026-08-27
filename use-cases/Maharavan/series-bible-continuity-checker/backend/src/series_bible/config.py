from functools import lru_cache
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "Series Bible & Continuity Checker"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://series_bible:series_bible@db:5432/series_bible"
    allowed_origins: list[str] = ["http://localhost:5173"]
    max_upload_bytes: int = 25 * 1024 * 1024
    superdocs_mcp_url: str = "https://api.superdocs.app/mcp"
    superdocs_mcp_api_key: SecretStr | None = None
    superdocs_mcp_timeout_seconds: float = 300
    superdocs_job_poll_seconds: float = 1
    superdocs_job_timeout_seconds: float = 90
    extraction_provider: str = "grounded_rules"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr | None = None
    llm_model: str = "gpt-4.1-mini"
    api_auth_token: SecretStr | None = None
    google_client_id: str | None = None
    jwt_secret: SecretStr | None = None
    jwt_expiry_hours: int = 168

@lru_cache
def get_settings() -> Settings:
    return Settings()
