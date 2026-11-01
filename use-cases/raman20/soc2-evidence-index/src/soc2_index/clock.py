from __future__ import annotations

import os
from datetime import datetime, timezone


def generated_at(override: str | None = None) -> str:
    if override:
        return override
    raw = os.environ.get("SOURCE_DATE_EPOCH")
    if raw is not None and raw != "":
        seconds = int(raw)
        return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")
