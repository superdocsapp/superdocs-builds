from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SK = re.compile(r"sk_[0-9a-f]{32}")
_LCE = re.compile(r"lce_[A-Za-z0-9]{16,}")


def redact(value: str) -> str:
    out = value
    out = re.sub(r"(?i)(authorization:\s*bearer\s+)\S+", r"\1[redacted]", out)
    out = _SK.sub("[redacted]", out)
    out = _LCE.sub("[redacted]", out)
    return out


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() == "authorization":
            out[k] = "Bearer [redacted]"
        else:
            out[k] = redact(v)
        if _SK.search(v) or _LCE.search(v):
            out[k] = "[redacted]" if k.lower() != "authorization" else "Bearer [redacted]"
    return out


class JsonlLogger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path

    def log(self, event: str, **fields: Any) -> None:
        rec = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "event": event}
        rec.update(fields)
        line = redact(json.dumps(rec, default=str))
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
