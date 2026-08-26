from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql+psycopg://docdesk:docdesk@localhost:5432/docdesk"

    slack_bot_token: str = ""
    slack_signing_secret: str = ""

    superdocs_api_key: str = ""
    superdocs_api_base_url: str = "https://api.superdocs.app"

    app_port: int = 8000


settings = Settings()
