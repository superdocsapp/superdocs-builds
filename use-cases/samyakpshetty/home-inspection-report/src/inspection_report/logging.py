"""Structured logging with mandatory redaction of secrets *and* photo URLs.

Two guarantees:

* **Structured** — one JSON object per line with a stable schema, so runs are greppable and a
  correlation id (``inspection_id``) threads a whole report together.
* **Redacted** — a filter scrubs every line before it is emitted. Two classes of thing get
  scrubbed, and the second is specific to this build:

  1. API keys (``sk_`` / ``lce_``) and ``Authorization: Bearer`` headers.
  2. **Photo URLs.** A SuperDocs image URL is a capability: I verified that fetching one with
     no Authorization header at all returns the full image bytes, and the URL never expires.
     These are photographs of a client's home, so the URL is as sensitive as the photo. It
     never reaches a log line, an error message, or a traceback.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk_[A-Za-z0-9]{6,}"),
    re.compile(r"lce_[A-Za-z0-9]{6,}"),
    re.compile(r"(?i)(bearer)\s+[A-Za-z0-9._\-]+"),
)

# Any URL into the image bucket, signed or not. Matched greedily enough to swallow a
# pre-signed query string so a signature can never trail out the back of the redaction.
_PHOTO_URL = re.compile(r"https?://[^\s\"'<>]*superdocs-document-images[^\s\"'<>]*")

_REDACTED = "***REDACTED***"
_PHOTO_REDACTED = "***PHOTO-URL-REDACTED***"

_RESERVED = frozenset(
    logging.makeLogRecord({}).__dict__.keys() | {"message", "asctime", "taskName"}
)


def redact(text: str) -> str:
    """Scrub secret-shaped substrings and photo capability URLs from ``text``."""
    text = _PHOTO_URL.sub(_PHOTO_REDACTED, text)
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
        return redact(f"{record.levelname:<7} {record.name}: {record.getMessage()}{suffix}")


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


# Keys `logging` already owns on a LogRecord. Passing one in `extra=` does not shadow it —
# it raises KeyError from inside the logging call, which means a log line takes down the
# thing it was describing. It cost a whole boot to find: `extra={"name": ...}` in the
# migration runner turned a working migration into a startup failure reported as a database
# outage. Renaming the two offenders fixes the two; refusing the key fixes the class.
_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class _SafeExtraLogger(logging.Logger):
    """A logger that will not let a reserved key in ``extra`` take a request down.

    The key is renamed rather than dropped, so the value still reaches the log line and the
    mistake is visible in it — the alternative is losing the field silently, which is how you
    end up debugging by absence.
    """

    def makeRecord(  # type: ignore[override]
        self,
        name: str,
        level: int,
        fn: str,
        lno: int,
        msg: object,
        args: Any,
        exc_info: Any,
        func: str | None = None,
        extra: dict[str, Any] | None = None,
        sinfo: str | None = None,
    ) -> logging.LogRecord:
        if extra:
            clashes = _RESERVED & extra.keys()
            if clashes:
                extra = {(f"extra_{k}" if k in clashes else k): v for k, v in extra.items()}
                extra["logging_key_clash"] = ",".join(sorted(clashes))
        return super().makeRecord(name, level, fn, lno, msg, args, exc_info, func, extra, sinfo)


logging.setLoggerClass(_SafeExtraLogger)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
