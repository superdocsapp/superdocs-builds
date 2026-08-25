"""Application configuration."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class Config:
    """Application configuration."""

    log_level: str = "INFO"
    corpus_path: str = "corpus"

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        load_dotenv()
        return cls(
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            corpus_path=os.getenv("CORPUS_PATH", "corpus"),
        )


def get_config() -> Config:
    """Get the current application configuration."""
    return Config.from_env()
