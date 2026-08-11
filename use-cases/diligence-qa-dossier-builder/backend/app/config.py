from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    APP_ENV: str = "development"
    DEBUG: bool = True
    
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "diligence_user"
    DB_PASSWORD: str = "diligence_password"
    DB_NAME: str = "diligence_db"
    
    DATABASE_URL: str = "postgresql+asyncpg://diligence_user:diligence_password@localhost:5432/diligence_db"

    # Ingestion & In-Memory Upload storage settings
    UPLOAD_DIR: str = "data/uploads"

    # Embedding configuration settings
    EMBEDDING_PROVIDER: str = "mock"
    EMBEDDING_DIMENSION: int = 1536

    # API keys placeholder (optional for now)
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
