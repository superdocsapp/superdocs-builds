from __future__ import annotations

import json
import logging

from notion_review.logging import (
    ConsoleFormatter,
    JsonFormatter,
    RedactionFilter,
    redact,
)


def _record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_redact_scrubs_every_secret_shape() -> None:
    dirty = "key=sk_abcdef123456 notion=ntn_ZZZ999888 legacy=secret_qwerty123 auth=Bearer tok_9"
    clean = redact(dirty)
    assert "sk_abcdef123456" not in clean
    assert "ntn_ZZZ999888" not in clean
    assert "secret_qwerty123" not in clean
    assert "tok_9" not in clean
    assert "***REDACTED***" in clean


def test_json_formatter_is_structured_and_redacted() -> None:
    line = JsonFormatter().format(
        _record("uploading with sk_deadbeef00ff", round_id="round_1", ops_spent=2)
    )
    parsed = json.loads(line)  # must be valid JSON
    assert parsed["round_id"] == "round_1"
    assert parsed["ops_spent"] == 2
    assert parsed["level"] == "INFO"
    assert "sk_deadbeef00ff"[:8] not in line  # the secret never survives
    assert "***REDACTED***" in parsed["msg"]


def test_console_formatter_includes_extras_and_redacts() -> None:
    line = ConsoleFormatter().format(_record("token ntn_secret999xyz", round_id="round_2"))
    assert "ntn_secret999xyz" not in line
    assert "round_2" in line


def test_redaction_filter_mutates_message() -> None:
    record = _record("bearer sk_live_9988776655")
    assert RedactionFilter().filter(record) is True
    assert "sk_live_9988776655" not in str(record.msg)
