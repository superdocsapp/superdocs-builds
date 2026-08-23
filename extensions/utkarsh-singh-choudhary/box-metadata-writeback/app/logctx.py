"""Structured logging: every log line emitted during a run carries the
same trace_id, so an operator (or a log aggregator query) can pull the
complete story of one file's processing -- webhook receipt, every stage,
every retry, the final commit -- instead of grep'ing timestamps and
guessing which lines belong together across concurrent runs.

Uses a contextvar rather than passing trace_id through every function
signature: the pipeline's stage methods, the retry helper, and the
circuit breaker all log without needing to know about tracing at all --
JsonLogFormatter reads whatever trace_id is current at format time.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Optional

_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)


def new_trace_id() -> str:
    return f"trace-{uuid.uuid4().hex[:12]}"


def set_trace_id(trace_id: Optional[str] = None) -> str:
    tid = trace_id or new_trace_id()
    _trace_id.set(tid)
    return tid


def current_trace_id() -> Optional[str]:
    return _trace_id.get()


class TraceIdFilter(logging.Filter):
    """Attaches the current contextvar trace_id to every LogRecord that
    passes through a handler with this filter installed, defaulting to
    '-' so the format string never breaks on records logged outside any
    run (startup, shutdown)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = current_trace_id() or "-"
        return True


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line -- ingestable by any log pipeline
    (CloudWatch, Datadog, ELK) without a custom parser, and greppable
    with `jq` locally. Falls back gracefully if trace_id was never set
    on the record (TraceIdFilter always sets it when installed, but a
    formatter shouldn't hard-crash if it's ever used without the
    filter)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": getattr(record, "trace_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    handler.addFilter(TraceIdFilter())
    if json_output:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(trace_id)s]: %(message)s")
        )
    root.addHandler(handler)
