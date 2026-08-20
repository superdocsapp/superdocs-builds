import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Disruption Re-Issue Engine"
    API_V1_STR: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/traveldb"

    # SuperDocs Platform
    SUPERDOCS_API_KEY: Optional[str] = None
    SUPERDOCS_BASE_URL: str = "https://api.superdocs.app"

    # AI Model Configurations
    OPENAI_API_KEY: Optional[str] = None
    MODEL_NAME: str = "gpt-4o"

    # Operations & Budget Safety Guardrails
    BUDGET_LIMIT_USD: float = 10.0
    SMALL_SAMPLE_MODE: bool = True
    STOPPING_RULE_MAX_OP: int = 50

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )

settings = Settings()
