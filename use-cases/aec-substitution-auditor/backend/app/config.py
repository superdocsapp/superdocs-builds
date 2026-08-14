import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    SUPERDOCS_API_KEY: str = Field(..., validation_alias="SUPERDOCS_API_KEY")
    DATABASE_URL: str = Field(..., validation_alias="DATABASE_URL")
    PORT: int = Field(8000, validation_alias="PORT")
    HOST: str = Field("127.0.0.1", validation_alias="HOST")
    USE_PGVECTOR: bool = Field(False, validation_alias="USE_PGVECTOR")

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def model_post_init(self, __context):
        if self.DATABASE_URL.startswith("postgresql://"):
            self.DATABASE_URL = self.DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

settings = Settings()
