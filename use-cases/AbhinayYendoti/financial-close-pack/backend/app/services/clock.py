from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
