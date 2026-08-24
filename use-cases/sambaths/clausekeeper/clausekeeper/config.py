import os
from pathlib import Path


def _parse_env_line(line: str):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    if line.startswith("export "):
        line = line[len("export "):].strip()
    key, _, value = line.partition("=")
    value = value.split(" #")[0].strip().strip("'").strip('"')
    return key.strip(), value


def _load_project_env():
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        parsed = _parse_env_line(line)
        if parsed:
            os.environ.setdefault(*parsed)


_load_project_env()

DEFAULT_BASE_URL = "https://api.superdocs.app"
OPS_SAFETY_FLOOR = int(os.environ.get("CK_OPS_FLOOR", "50"))
MAX_TURNS_PER_RUN = int(os.environ.get("CK_MAX_TURNS", "12"))
POLL_INTERVAL_S = float(os.environ.get("CK_POLL_INTERVAL", "2"))

LATENCY = {
    "single_section_edit": {"warn_after": 10, "max_wait": 120},
    "complex_edit": {"warn_after": 120, "max_wait": 900},
    "verification_turn": {"warn_after": 30, "max_wait": 300},
}


def api_key() -> str:
    return os.environ.get("SUPERDOCS_API_KEY", "")


def base_url() -> str:
    return os.environ.get("SUPERDOCS_BASE_URL", DEFAULT_BASE_URL)
