"""Tests for Outer + Inner Double JSON Deserialization of Proposed Diffs."""

import json
import pytest
from src.superdocs_client import (
    extract_and_parse_diff,
    DiffParsingError,
    SuperDocsClient,
)


def test_standard_double_json_payload_extraction():
    """Verify that a JSON-encoded string inside outer response['diff'] is correctly parsed."""
    inner_diff = {
        "target": "evaluation_section",
        "action": "replace_boundaries",
        "timestamp_updated": True,
        "changes": [
            {"type": "section_replace", "section": "evaluation_tables"},
            {"type": "timestamp_update", "timestamp": "2026-08-17 12:00:00 UTC"}
        ]
    }
    
    # Outer JSON response where 'diff' is a stringified JSON
    outer_response = {
        "document_id": "doc_12345",
        "status": "diff_proposed",
        "diff": json.dumps(inner_diff)  # First level of string encoding
    }

    # Deserialization test
    result = extract_and_parse_diff(outer_response)
    
    assert isinstance(result, dict)
    assert result["target"] == "evaluation_section"
    assert result["action"] == "replace_boundaries"
    assert len(result["changes"]) == 2
    assert result["changes"][0]["section"] == "evaluation_tables"


def test_double_encoded_json_string_input():
    """Verify deserialization when the entire payload is a JSON string containing an inner JSON string."""
    inner_data = {"applied_patches": ["eval_table", "run_id"], "version": 2}
    inner_string = json.dumps(inner_data)
    
    # Outer envelope as string containing inner string
    outer_envelope = {"diff": inner_string}
    full_string_payload = json.dumps(outer_envelope)

    result = extract_and_parse_diff(full_string_payload)
    
    assert isinstance(result, dict)
    assert result["applied_patches"] == ["eval_table", "run_id"]
    assert result["version"] == 2


def test_nested_data_proposed_diff_field():
    """Verify deserialization when diff is in data.proposed_diff field."""
    inner_diff = {"metric_count": 9, "status": "valid"}
    outer_response = {
        "data": {
            "proposed_diff": json.dumps(inner_diff)
        }
    }

    result = extract_and_parse_diff(outer_response)
    assert result == inner_diff


def test_already_deserialized_dict():
    """Verify that if the diff is already a plain dict, it is returned without error."""
    plain_diff = {"status": "ok", "changes": []}
    outer = {"diff": plain_diff}

    result = extract_and_parse_diff(outer)
    assert result == plain_diff


def test_invalid_inner_json_raises_diff_parsing_error():
    """Verify that corrupt inner JSON string raises DiffParsingError."""
    outer_corrupt = {
        "document_id": "doc_999",
        "diff": "{not valid json: missing quotes}"
    }

    with pytest.raises(DiffParsingError) as exc_info:
        extract_and_parse_diff(outer_corrupt)
    assert "Failed second JSON parse" in str(exc_info.value)


def test_empty_or_none_diff_raises_error():
    """Verify that None payload raises DiffParsingError."""
    with pytest.raises(DiffParsingError):
        extract_and_parse_diff(None)


def test_superdocs_client_approve_workflow_with_double_json():
    """Verify end-to-end client approve() call correctly consumes double JSON encoded chat response."""
    client = SuperDocsClient(mock_mode=True)
    
    # 1. Upload
    up_res = client.upload(
        content="# Test Model\n<!-- EVALUATION_SECTION_START -->\nold\n<!-- EVALUATION_SECTION_END -->",
        title="Test Doc"
    )
    doc_id = up_res["document_id"]

    # 2. Chat (returns response with stringified diff in 'diff' field)
    chat_res = client.chat(
        document_id=doc_id,
        instruction="Update evaluation table",
        evaluation_markdown="| Task | Score |\n| MMLU | 90% |"
    )

    assert isinstance(chat_res["diff"], str), "Chat response diff must be a string in the outer JSON"

    # 3. Approve consumes chat_res and performs 2x parse
    app_res = client.approve(document_id=doc_id, chat_response_or_diff=chat_res)

    assert app_res["status"] == "approved"
    assert app_res["version"] == 2
