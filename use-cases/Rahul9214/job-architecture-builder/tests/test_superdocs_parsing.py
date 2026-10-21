"""Regression tests for proposed-change parsing, including the double-JSON trap."""

from __future__ import annotations

import json

import pytest

from job_architecture.superdocs.errors import ProposedChangeParseError
from job_architecture.superdocs.parsing import (
    extract_pending_changes_from_job,
    header_safe_for_log,
    map_job_status,
    parse_pending_changes,
    redact_secrets,
)

CHANGE = {
    "change_id": "ch_1",
    "operation": "edit",
    "chunk_id": "chunk_a",
    "document_id": "doc_1",
    "old_html": "<p>before</p>",
    "new_html": "<p>after</p>",
    "ai_explanation": "Tighten the wording",
}


def test_already_decoded_object():
    parsed = parse_pending_changes([CHANGE])
    assert len(parsed) == 1
    assert parsed[0].change_id == "ch_1"
    assert parsed[0].before == "<p>before</p>"
    assert parsed[0].after == "<p>after</p>"
    assert parsed[0].reason == "Tighten the wording"


def test_json_encoded_string():
    parsed = parse_pending_changes(json.dumps([CHANGE]))
    assert parsed[0].change_id == "ch_1"


def test_double_json_encoded_string():
    inner = json.dumps([CHANGE])
    parsed = parse_pending_changes(json.dumps(inner))
    assert parsed[0].operation == "edit"
    assert parsed[0].document_id == "doc_1"


def test_wrapped_object_with_changes_key():
    parsed = parse_pending_changes({"changes": [CHANGE]})
    assert parsed[0].change_id == "ch_1"


def test_item_that_is_itself_a_json_string():
    parsed = parse_pending_changes([json.dumps(CHANGE)])
    assert parsed[0].change_id == "ch_1"


def test_explicit_empty_list_is_valid():
    assert parse_pending_changes([]) == ()


def test_malformed_json_is_an_error_not_empty():
    with pytest.raises(ProposedChangeParseError):
        parse_pending_changes("{not-json")


def test_missing_payload_is_an_error_not_empty():
    with pytest.raises(ProposedChangeParseError):
        parse_pending_changes(None)


def test_missing_required_fields_is_an_error():
    with pytest.raises(ProposedChangeParseError):
        parse_pending_changes([{"old_html": "<p>x</p>"}])


def test_hitl_job_missing_pending_changes_is_an_error():
    with pytest.raises(ProposedChangeParseError):
        extract_pending_changes_from_job(
            {"status": "awaiting_approval", "metadata": {}}
        )


def test_continue_prompt_has_no_pending_changes():
    parsed = extract_pending_changes_from_job(
        {
            "status": "awaiting_approval",
            "metadata": {"awaiting_kind": "continue_prompt"},
        }
    )
    assert parsed is None


def test_pending_changes_json_string_on_job():
    parsed = extract_pending_changes_from_job(
        {
            "status": "awaiting_approval",
            "metadata": {"pending_changes": json.dumps([CHANGE])},
        }
    )
    assert parsed is not None
    assert parsed[0].change_id == "ch_1"


def test_map_job_status():
    assert map_job_status("pending") == "queued"
    assert map_job_status("in_progress") == "processing"
    assert map_job_status("awaiting_approval") == "awaiting_approval"
    assert map_job_status("completed") == "completed"
    assert map_job_status("failed") == "failed"


def test_secret_redaction():
    secret = "sk_test_offline_not_a_real_key"
    assert secret not in redact_secrets(f"rejected {secret}", secret)
    assert header_safe_for_log("Authorization", f"Bearer {secret}") == "[redacted]"
    assert header_safe_for_log("Retry-After", "2") == "2"
