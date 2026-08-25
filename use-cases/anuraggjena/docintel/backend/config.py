import os
import secrets
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), ".env"),
        env_file_encoding="utf-8"
    )

    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/docintel"

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql://"):
            raise ValueError("database_url must start with postgresql://")
        return v

    # Auth
    secret_key: str = "CHANGE_ME_IN_PRODUCTION"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    stream_token_expire_seconds: int = 60
    secure_cookies: bool = True  # Set to False for local HTTP development

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        # Generate secure random key if not set (for development only)
        if not v or v == "":
            import warnings
            generated_key = secrets.token_urlsafe(32)
            warnings.warn(
                f"SECRET_KEY not set - generated random key for development: {generated_key[:16]}..."
            )
            return generated_key

        # Check if still using default placeholder
        if v == "CHANGE_ME_IN_PRODUCTION":
            # In production, this should be an error
            if os.getenv("ENVIRONMENT", "development").lower() == "production":
                raise ValueError(
                    "SECRET_KEY must be changed from default value in production"
                )
            # In development, generate a secure key
            import warnings
            generated_key = secrets.token_urlsafe(32)
            warnings.warn(
                f"Using default SECRET_KEY - generated random key for development: {generated_key[:16]}..."
            )
            return generated_key

        # Validate minimum length
        if len(v) < 32:
            raise ValueError(
                f"SECRET_KEY must be at least 32 characters long, got {len(v)}"
            )

        return v

    # Storage
    storage_path: str = "./storage"

    # AI
    groq_api_key: str = ""
    cerebras_api_key: str = ""
    gemini_api_key: str = ""
    gemini_primary_model: str = "gemini-3.1-flash-lite"
    gemini_fallback_models: str = "gemini-3.5-flash-lite,gemini-3.5-flash"
    llm_provider: str = "gemini"  # "groq", "cerebras", or "gemini"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    @field_validator("groq_api_key")
    @classmethod
    def validate_groq_api_key(cls, v: str) -> str:
        if not v and cls is not None:
            import warnings
            warnings.warn("GROQ_API_KEY not set - AI features will not work")
        return v

    # SuperDocs (Phase 7 - Optional)
    superdocs_api_key: str = ""
    superdocs_api_url: str = "https://api.superdocs.app"

    @field_validator("superdocs_api_key")
    @classmethod
    def validate_superdocs_api_key(cls, v: str) -> str:
        if not v:
            import warnings
            warnings.warn("SUPERDOCS_API_KEY not set - SuperDocs integration disabled")
        return v

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = True
    log_level: str = "INFO"

    # CORS
    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
