import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable overrides."""
    
    APP_NAME: str = "SuperDocs Supplier ESG Attestation Engine"
    API_V1_STR: str = "/api/v1"
    ENV: str = "development"
    DEBUG: bool = True
    
    # Database connection URL (defaults to async SQLite if Postgres is not running, or PostgreSQL)
    DATABASE_URL: str = "sqlite+aiosqlite:///./task2_esg.db"
    
    # SuperDocs Platform Configuration
    SUPERDOCS_API_BASE_URL: str = "https://api.superdocs.app/v1"
    SUPERDOCS_API_KEY: str | None = None
    SUPERDOCS_MOCK_MODE: bool = True  # True allows testing without API usage/costs
    
    # LLM Settings (for intelligent normalization & parsing fallbacks)
    LITELLM_API_KEY: str | None = None
    LITELLM_MODEL: str = "groq/llama-3.1-8b-instant"
    
    # Storage Paths
    STORAGE_DIR: str = "storage"
    TEMPLATES_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
    UPLOADS_DIR: str = "storage/uploads"
    EXPORTS_DIR: str = "storage/exports"
    
    # CORS
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3030",
        "http://localhost:3031",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3030",
        "http://127.0.0.1:3031",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "*",
    ]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()

# Ensure directories exist
for path in [settings.STORAGE_DIR, settings.UPLOADS_DIR, settings.EXPORTS_DIR]:
    os.makedirs(path, exist_ok=True)
