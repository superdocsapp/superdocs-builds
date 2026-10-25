from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class Settings(BaseSettings):

    database_url: str = "sqlite:///./submittal.db"

    openai_api_key: str | None = None

    superdocs_api_key: str | None = None

    superdocs_base_url: str = (
        "https://api.superdocs.app"
    )

    app_env: str = "development"

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()