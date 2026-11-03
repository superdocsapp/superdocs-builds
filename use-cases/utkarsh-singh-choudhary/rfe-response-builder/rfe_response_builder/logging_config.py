"""
Structured logging for this package.

Before this module, every entrypoint (`generate.py`'s CLI, `webapp/app.py`)
called `logging.basicConfig` with a plain text formatter -- readable in a
terminal, but not machine-parseable, so answering "why did case X fail"
in production meant grepping free-text log lines instead of querying
structured fields. This module adds a JSON formatter and two
`contextvars`-based correlation IDs (`case_id`, `request_id`) that get
attached to every log record emitted while a case/request is being
processed, so logs from one case (across the notice-parsing, matching,
per-item drafting, and export steps) can be correlated even when they
interleave with other cases' logs from other gunicorn worker threads.

Falls back to the original plain-text format when `JSON_LOGS` is unset
or falsy, so local development output stays human-readable by default;
set `JSON_LOGS=1` (already the default in render.yaml) for production.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import time

_case_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("case_id", default=None)
_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def set_case_id(case_id: str | None) -> None:
    _case_id_var.set(case_id)


def set_request_id(request_id: str | None) -> None:
    _request_id_var.set(request_id)


def get_case_id() -> str | None:
    return _case_id_var.get()


def get_request_id() -> str | None:
    return _request_id_var.get()


class _ContextFilter(logging.Filter):
    """Attaches the current case_id/request_id (if any) to every record
    so the formatter can include them without every call site having to
    pass them explicitly via `extra=`."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.case_id = _case_id_var.get()
        record.request_id = _request_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        case_id = getattr(record, "case_id", None)
        request_id = getattr(record, "request_id", None)
        if case_id:
            payload["case_id"] = case_id
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(default_level: str = "INFO") -> None:
    """Call once at process startup (CLI `main()`, webapp module import).
    Idempotent-ish: clears and re-adds handlers on the root logger rather
    than stacking duplicate handlers if called more than once (e.g. under
    a test runner that imports the webapp module multiple times)."""
    level_name = os.environ.get("LOG_LEVEL", default_level).upper()
    level = getattr(logging, level_name, logging.INFO)
    use_json = os.environ.get("JSON_LOGS", "").lower() in {"1", "true", "yes"}

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.addFilter(_ContextFilter())
    if use_json:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s [case=%(case_id)s req=%(request_id)s]: %(message)s"
        ))
    root.addHandler(handler)
