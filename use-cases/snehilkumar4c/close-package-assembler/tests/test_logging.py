"""Logging must redact sensitive fields and bind a run ID — see core/logging.py."""

from __future__ import annotations

import io
import json
import sys

from core.logging import bind_run_id, clear_run_context, configure_logging, get_logger


def test_redaction_and_run_id_binding() -> None:
    configure_logging("INFO")
    bind_run_id("run-test-1", stage="extract")
    log = get_logger("test")

    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        log.info(
            "doc_processed",
            document_html="<p>SECRET CONTRACT TEXT</p>",
            section_count=5,
            ssn="123-45-6789",
        )
    finally:
        sys.stdout = old_stdout
        clear_run_context()

    data = json.loads(buf.getvalue().strip())
    assert data["document_html"] == "[REDACTED]"
    assert data["ssn"] == "[REDACTED]"
    assert data["run_id"] == "run-test-1"
    assert data["stage"] == "extract"
    # Non-sensitive fields must pass through untouched.
    assert data["section_count"] == 5
