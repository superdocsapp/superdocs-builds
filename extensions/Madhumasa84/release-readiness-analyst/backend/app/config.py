from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./release_readiness.db")
    artifact_dir: Path = Path(os.getenv("ARTIFACT_DIR", "./artifacts"))
    embedding_dimensions: int = int(os.getenv("EMBEDDING_DIMENSIONS", "384"))
    max_source_bytes: int = int(os.getenv("MAX_SOURCE_BYTES", str(10 * 1024 * 1024)))
    stage_budget_seconds: float = float(os.getenv("STAGE_BUDGET_SECONDS", "30"))


settings = Settings()
settings.artifact_dir.mkdir(parents=True, exist_ok=True)
