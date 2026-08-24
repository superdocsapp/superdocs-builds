from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str = ".env") -> None:
    file = Path(path)
    if not file.exists():
        return
    for line in file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    db_path: str = "benchmark.db"
    api_key: str | None = None
    base_url: str = "https://api.superdocs.app"
    client_mode: str = "real"
    max_batch_cases: int = 60
    max_batch_operations: int = 60
    poll_interval_seconds: float = 1.0
    poll_timeout_seconds: float = 180.0

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            db_path=os.getenv("BENCHMARK_DB_PATH", "benchmark.db"),
            api_key=os.getenv("SUPERDOCS_API_KEY"),
            base_url=os.getenv("SUPERDOCS_BASE_URL", "https://api.superdocs.app").rstrip("/"),
            client_mode=os.getenv("SUPERDOCS_CLIENT", "real"),
            max_batch_cases=int(os.getenv("BENCHMARK_MAX_BATCH_CASES", "60")),
            max_batch_operations=int(os.getenv("BENCHMARK_MAX_BATCH_OPERATIONS", "60")),
            poll_interval_seconds=float(os.getenv("SUPERDOCS_POLL_INTERVAL_SECONDS", "1")),
            poll_timeout_seconds=float(os.getenv("SUPERDOCS_POLL_TIMEOUT_SECONDS", "180")),
        )
