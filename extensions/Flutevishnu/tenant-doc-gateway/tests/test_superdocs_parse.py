"""The double-parse: proposed changes arrive as a JSON-encoded STRING."""

from __future__ import annotations

import json

from app.integrations.superdocs.client import SuperDocsClient


def test_parse_changes_double_decodes_json_string():
    changes = [{"change_id": "c1", "new_html": "<p>x</p>"}]
    # SuperDocs sends this field as a STRING, not a list.
    encoded_as_string = json.dumps(changes)
    parsed = SuperDocsClient.parse_changes(encoded_as_string)
    assert parsed == changes


def test_parse_changes_handles_none_and_garbage():
    assert SuperDocsClient.parse_changes(None) == []
    assert SuperDocsClient.parse_changes("not-json") == []


def test_parse_changes_handles_nested_changes_key():
    inner = json.dumps([{"change_id": "c9"}])
    assert SuperDocsClient.parse_changes({"changes": inner}) == [{"change_id": "c9"}]


def test_parse_changes_passes_through_plain_list():
    changes = [{"change_id": "c2"}]
    assert SuperDocsClient.parse_changes(changes) == changes


def test_to_job_result_reads_metadata_and_result_nested_fields():
    client = SuperDocsClient(base_url="http://test", api_key="k")
    raw = {
        "job_id": "j1",
        "session_id": "s1",
        "status": "awaiting_approval",
        "metadata": {
            "pending_changes": [
                {"change_id": "pc1", "operation": "edit", "chunk_id": "c-1"}
            ]
        },
        "result": {
            "document_changes": {"updated_html": "<p>done</p>"},
            "usage": {"ops_charged": 1},
        },
    }
    job = client._to_job_result(raw)
    assert job.job_id == "j1"
    assert job.session_id == "s1"
    assert len(job.pending_changes) == 1
    assert job.pending_changes[0]["change_id"] == "pc1"
    assert job.document_html == "<p>done</p>"
    assert job.ops_cost == 1.0
