from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str = "https://api.superdocs.app"
    request_timeout_seconds: float = 300.0
    poll_interval_seconds: float = 1.0
    job_timeout_seconds: float = 300.0

    @classmethod
    def from_environment(cls) -> Settings:
        load_dotenv()
        api_key = os.getenv("SUPERDOCS_API_KEY", "").strip()
        if not api_key or api_key == "your-key-here":
            raise RuntimeError(
                "SUPERDOCS_API_KEY is not configured. Put it in a local .env file; "
                "never commit or paste the key into source code."
            )
        return cls(
            api_key=api_key,
            base_url=os.getenv("SUPERDOCS_BASE_URL", cls.base_url).rstrip("/"),
        )
