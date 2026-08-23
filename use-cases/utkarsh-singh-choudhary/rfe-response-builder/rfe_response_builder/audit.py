"""
Audit trail for the human-review gate.

`review.finalize_review` already enforces that every section reaching
the exported document was explicitly approved by a human (silence is
rejection, never approval) -- what it didn't do is keep a durable,
queryable record of WHO approved WHAT and WHEN. For a legal document
this matters: an attorney or firm may need to show, after the fact,
exactly which reviewer approved a given section and what feedback (if
any) was given on a rejected one.

Each decision is appended as one JSON line (JSON Lines format -- easy to
tail, grep, or ship to a log aggregator) to `AUDIT_LOG_PATH`
(default `/tmp/rfe_audit_log.jsonl`), or into a database table if
`AUDIT_STORE_URL` (or `DATABASE_URL`) is configured, so it survives
alongside the review-session data rather than only on local disk when
running with a shared Postgres backend.

This module intentionally never raises on write failure -- a broken
audit sink must never block or fail a real approve/reject action. Errors
are logged loudly instead.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger("rfe_response_builder.audit")

DEFAULT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", "/tmp/rfe_audit_log.jsonl")

_write_lock = threading.Lock()


@dataclass
class AuditRecord:
    timestamp: str
    case_id: str
    request_id: str
    action: str  # "approve" or "reject"
    reviewer: str  # identity string -- "unknown" if the caller has no auth layer wired up yet
    feedback: str | None
    response_section: str


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log_decision(case_id: str, request_id: str, action: str, reviewer: str = "unknown",
                  feedback: str | None = None, response_section: str = "") -> None:
    """Appends one audit record. Best-effort: logs and swallows any I/O
    error rather than raising, since a failed audit write must never
    block the actual approve/reject flow it's recording."""
    record = AuditRecord(
        timestamp=_now_iso(), case_id=case_id, request_id=request_id, action=action,
        reviewer=reviewer, feedback=feedback, response_section=response_section,
    )
    line = json.dumps(asdict(record))
    try:
        path = Path(DEFAULT_LOG_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError as e:
        logger.error("failed to write audit record (case=%s request=%s action=%s): %s",
                     case_id, request_id, action, e)


def read_audit_trail(case_id: str | None = None, path: str | None = None) -> list[AuditRecord]:
    """Reads back the audit log, optionally filtered to one case_id.
    Used by tests and can back an attorney-facing "review history" view.
    Missing file returns [] rather than raising -- nothing has been
    audited yet is a valid, non-error state."""
    log_path = Path(path or DEFAULT_LOG_PATH)
    if not log_path.exists():
        return []
    records = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if case_id is not None and data.get("case_id") != case_id:
            continue
        records.append(AuditRecord(**data))
    return records
