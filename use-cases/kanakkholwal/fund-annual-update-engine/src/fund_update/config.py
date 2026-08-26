"""Settings, read from the environment. No key ever has a default."""

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(slots=True)
class Settings:
    api_key: str
    api_base: str
    max_operations: int
    sample: int
    baseline_dir: Path
    data_file: Path
    out_dir: Path

    @property
    def has_key(self) -> bool:
        return bool(self.api_key.strip())


def load_settings(root: Path | None = None) -> Settings:
    root = root or Path.cwd()
    _load_dotenv(root / ".env")
    return Settings(
        api_key=os.environ.get("SUPERDOCS_API_KEY", ""),
        api_base=os.environ.get("SUPERDOCS_API_BASE", "https://api.superdocs.app"),
        max_operations=int(os.environ.get("FUND_UPDATE_MAX_OPERATIONS", "25")),
        sample=int(os.environ.get("FUND_UPDATE_SAMPLE", "0")),
        baseline_dir=root / "fixtures" / "baseline",
        data_file=root / "fixtures" / "data" / "figures-2025.csv",
        out_dir=root / "out",
    )
