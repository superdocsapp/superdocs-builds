"""Runtime settings. Environment first, ``.env`` as a fallback, no secrets on disk."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STATE_DIR = "state"
DEFAULT_OUT_DIR = "out"


def load_dotenv(path: str | os.PathLike[str] = ".env") -> None:
    """Read ``.env`` into the environment without overwriting anything already set.

    Real environment always wins, so a shell export beats a stale file.
    """
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    state_dir: Path
    out_dir: Path

    @property
    def ledger_path(self) -> Path:
        return self.state_dir / "longhaul.db"

    def redacted(self) -> str:
        """Never print a key. Enough to tell two keys apart, not enough to use one."""
        if not self.api_key:
            return "<unset>"
        return f"{self.api_key[:6]}…{self.api_key[-2:]} ({len(self.api_key)} chars)"


def load_settings(
    *, state_dir: str | None = None, out_dir: str | None = None, env_file: str = ".env"
) -> Settings:
    load_dotenv(env_file)
    return Settings(
        api_key=os.environ.get("SUPERDOCS_API_KEY", ""),
        base_url=os.environ.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app"),
        state_dir=Path(state_dir or os.environ.get("LONGHAUL_STATE_DIR", DEFAULT_STATE_DIR)),
        out_dir=Path(out_dir or os.environ.get("LONGHAUL_OUT_DIR", DEFAULT_OUT_DIR)),
    )
