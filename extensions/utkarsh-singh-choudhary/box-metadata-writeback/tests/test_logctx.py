"""Structured logging: trace_id propagation and JSON formatting."""
import json
import logging

from app.logctx import JsonLogFormatter, TraceIdFilter, current_trace_id, set_trace_id


def test_set_trace_id_returns_and_stores_it():
    tid = set_trace_id()
    assert tid.startswith("trace-")
    assert current_trace_id() == tid


def test_set_trace_id_accepts_an_explicit_value():
    set_trace_id("trace-fixed")
    assert current_trace_id() == "trace-fixed"


def test_json_formatter_embeds_current_trace_id():
    set_trace_id("trace-abc123")
    logger = logging.getLogger("test.logctx")
    record = logger.makeRecord("test.logctx", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    TraceIdFilter().filter(record)
    line = JsonLogFormatter().format(record)
    payload = json.loads(line)
    assert payload["trace_id"] == "trace-abc123"
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"


def test_json_formatter_defaults_trace_id_when_filter_not_applied():
    logger = logging.getLogger("test.logctx")
    record = logger.makeRecord("test.logctx", logging.INFO, __file__, 1, "no trace", (), None)
    line = JsonLogFormatter().format(record)
    payload = json.loads(line)
    assert payload["trace_id"] == "-"
