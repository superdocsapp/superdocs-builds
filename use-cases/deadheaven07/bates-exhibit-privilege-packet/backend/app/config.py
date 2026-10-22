from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    superdocs_api_key: str = "your-key-here"
    superdocs_base_url: str = "https://api.superdocs.app"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bates_packet"

    storage_root: Path = Path("./storage")
    originals_dir: str = "originals"
    processed_dir: str = "processed"
    working_dir: str = "working"
    final_dir: str = "final"

    tesseract_cmd: str = "tesseract"
    tesseract_lang: str = "eng"

    bates_prefix: str = "CASE-"
    bates_start_number: int = 1
    bates_padding: int = 6

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False
    log_level: str = "INFO"

    @property
    def originals_path(self) -> Path:
        return self.storage_root / self.originals_dir

    @property
    def processed_path(self) -> Path:
        return self.storage_root / self.processed_dir

    @property
    def working_path(self) -> Path:
        return self.storage_root / self.working_dir

    @property
    def final_path(self) -> Path:
        return self.storage_root / self.final_dir

    def ensure_directories(self) -> None:
        for path in [
            self.originals_path,
            self.processed_path,
            self.working_path,
            self.final_path,
        ]:
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()