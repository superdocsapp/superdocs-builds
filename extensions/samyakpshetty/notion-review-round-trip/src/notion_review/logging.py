"""Structured logging with mandatory secret redaction.

Two guarantees:

* **Structured** — one JSON object per line with a stable schema, so runs are greppable and
  a correlation id (``round_id``) threads a whole review round together.
* **Redacted** — a filter scrubs anything that looks like a SuperDocs (``sk_``) or Notion
  (``ntn_`` / ``secret_``) token, plus ``Authorization: Bearer`` headers, from *every* line
  before it is emitted. A key must never reach a log, per the task's ground rules.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

# Token shapes we never want to see in a log line. Redaction runs on the final rendered
# string, so it catches secrets wherever they hide: message, args, or structured extras.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk_[A-Za-z0-9]{6,}"),
    re.compile(r"ntn_[A-Za-z0-9]{6,}"),
    re.compile(r"secret_[A-Za-z0-9]{6,}"),
    re.compile(r"(?i)(bearer)\s+[A-Za-z0-9._\-]+"),
)
_REDACTED = "***REDACTED***"

# Attributes the stdlib puts on every LogRecord; anything else the caller passed via
# ``extra=`` is treated as structured context and included in the JSON payload.
_RESERVED = frozenset(
    logging.makeLogRecord({}).__dict__.keys() | {"message", "asctime", "taskName"}
)


def redact(text: str) -> str:
    """Scrub secret-shaped substrings from ``text``."""
    for pattern in _SECRET_PATTERNS:
        if pattern is _SECRET_PATTERNS[-1]:
            text = pattern.sub(rf"\1 {_REDACTED}", text)
        else:
            text = pattern.sub(_REDACTED, text)
    return text


class RedactionFilter(logging.Filter):
    """Belt-and-braces: redact the message even before formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        return True


class JsonFormatter(logging.Formatter):
    """Render each record as a single redacted JSON line with its structured extras."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, default=str, ensure_ascii=False))


class ConsoleFormatter(logging.Formatter):
    """Human-friendly single line for local runs; still redacted."""

    def format(self, record: logging.LogRecord) -> str:
        extras = {
            k: v for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")
        }
        suffix = f"  {extras}" if extras else ""
        base = f"{record.levelname:<7} {record.name}: {record.getMessage()}{suffix}"
        return redact(base)


def setup_logging(log_format: str = "json", level: int = logging.INFO) -> None:
    """Configure the root logger. Idempotent — safe to call more than once."""
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if log_format == "json" else ConsoleFormatter())
    handler.addFilter(RedactionFilter())
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
