"""
Tests for rfe_response_builder/logging_config.py.

Previously untested -- no test file existed for this module at all,
despite it being wired into both the CLI and webapp entrypoints in
every drafting run. These tests exercise the correlation-id context
vars directly and the JSON/plain-text formatter switch, since that's
exactly the kind of "wired in everywhere, verified nowhere directly"
surface that has produced real bugs elsewhere in this package this
session.
"""
import json
import logging

from rfe_response_builder.logging_config import (
    configure_logging,
    get_case_id,
    get_request_id,
    set_case_id,
    set_request_id,
)


def test_set_and_get_case_id_roundtrip():
    set_case_id("CASE-123")
    assert get_case_id() == "CASE-123"
    set_case_id(None)
    assert get_case_id() is None


def test_set_and_get_request_id_roundtrip():
    set_request_id("req-abc")
    assert get_request_id() == "req-abc"
    set_request_id(None)
    assert get_request_id() is None


def test_case_id_and_request_id_are_independent():
    set_case_id("CASE-1")
    set_request_id("req-1")
    assert get_case_id() == "CASE-1"
    assert get_request_id() == "req-1"
    set_case_id(None)
    set_request_id(None)


def test_configure_logging_plain_text_format(monkeypatch, capsys):
    monkeypatch.delenv("JSON_LOGS", raising=False)
    configure_logging()
    set_case_id("CASE-PLAIN")
    logger = logging.getLogger("test.plain")
    logger.error("something went wrong")
    set_case_id(None)
    captured = capsys.readouterr()
    assert "CASE-PLAIN" in captured.err
    assert "something went wrong" in captured.err
    # Plain format is not valid JSON -- confirms JSON_LOGS=unset really
    # does produce the human-readable format, not JSON.
    try:
        json.loads(captured.err.strip().splitlines()[-1])
        assert False, "expected plain text, not JSON"
    except json.JSONDecodeError:
        pass


def test_configure_logging_json_format(monkeypatch, capsys):
    monkeypatch.setenv("JSON_LOGS", "1")
    configure_logging()
    set_case_id("CASE-JSON")
    set_request_id("req-json-1")
    logger = logging.getLogger("test.json")
    logger.warning("a warning message")
    set_case_id(None)
    set_request_id(None)
    monkeypatch.delenv("JSON_LOGS", raising=False)
    configure_logging()  # restore plain format for any subsequent test in this process

    captured = capsys.readouterr()
    last_line = captured.err.strip().splitlines()[-1]
    record = json.loads(last_line)  # must be valid JSON
    assert record["message"] == "a warning message"
    assert record["level"] == "WARNING"
    assert record["case_id"] == "CASE-JSON"
    assert record["request_id"] == "req-json-1"


def test_configure_logging_json_format_omits_absent_correlation_ids(monkeypatch, capsys):
    monkeypatch.setenv("JSON_LOGS", "1")
    configure_logging()
    set_case_id(None)
    set_request_id(None)
    logger = logging.getLogger("test.json.no_ids")
    logger.info("no correlation ids set")
    monkeypatch.delenv("JSON_LOGS", raising=False)
    configure_logging()

    captured = capsys.readouterr()
    last_line = captured.err.strip().splitlines()[-1]
    record = json.loads(last_line)
    assert "case_id" not in record
    assert "request_id" not in record


def test_configure_logging_respects_log_level_env_var(monkeypatch, capsys):
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    monkeypatch.delenv("JSON_LOGS", raising=False)
    configure_logging()
    logger = logging.getLogger("test.level")
    logger.info("this should not appear")
    logger.error("this should appear")
    captured = capsys.readouterr()
    assert "this should not appear" not in captured.err
    assert "this should appear" in captured.err
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    configure_logging()  # restore default level for subsequent tests


def test_configure_logging_does_not_stack_duplicate_handlers(monkeypatch, capsys):
    """Calling configure_logging() more than once (e.g. re-imported under
    a test runner) must not cause each log line to be emitted multiple
    times."""
    monkeypatch.delenv("JSON_LOGS", raising=False)
    configure_logging()
    configure_logging()
    configure_logging()
    logger = logging.getLogger("test.no_dupes")
    logger.error("only once please")
    captured = capsys.readouterr()
    assert captured.err.count("only once please") == 1
