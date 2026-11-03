"""Tests for rfe_response_builder/audit.py."""
import json

from rfe_response_builder.audit import log_decision, read_audit_trail


def test_log_decision_writes_a_readable_record(tmp_path, monkeypatch):
    log_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr("rfe_response_builder.audit.DEFAULT_LOG_PATH", str(log_path))

    log_decision(case_id="CASE-1", request_id="1", action="approve", reviewer="jane@firm.com",
                 feedback=None, response_section="Some drafted text.")

    lines = log_path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["case_id"] == "CASE-1"
    assert record["request_id"] == "1"
    assert record["action"] == "approve"
    assert record["reviewer"] == "jane@firm.com"
    assert "timestamp" in record


def test_log_decision_never_raises_on_bad_path(monkeypatch):
    # Pointing at a path under a file (not a directory) makes mkdir fail --
    # log_decision must swallow this, never propagate to the caller.
    monkeypatch.setattr("rfe_response_builder.audit.DEFAULT_LOG_PATH", "/dev/null/impossible/audit.jsonl")
    log_decision(case_id="CASE-1", request_id="1", action="reject", reviewer="jane")  # must not raise


def test_read_audit_trail_filters_by_case_id(tmp_path, monkeypatch):
    log_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr("rfe_response_builder.audit.DEFAULT_LOG_PATH", str(log_path))

    log_decision(case_id="CASE-1", request_id="1", action="approve", reviewer="jane")
    log_decision(case_id="CASE-2", request_id="1", action="reject", reviewer="joe", feedback="needs more detail")

    all_records = read_audit_trail(path=str(log_path))
    assert len(all_records) == 2

    case_1_only = read_audit_trail(case_id="CASE-1", path=str(log_path))
    assert len(case_1_only) == 1
    assert case_1_only[0].reviewer == "jane"


def test_read_audit_trail_returns_empty_list_when_no_file_yet(tmp_path):
    assert read_audit_trail(path=str(tmp_path / "does_not_exist.jsonl")) == []


def test_read_audit_trail_skips_malformed_lines(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    log_path.write_text('{"bad json"\nnot even json at all\n')
    assert read_audit_trail(path=str(log_path)) == []
