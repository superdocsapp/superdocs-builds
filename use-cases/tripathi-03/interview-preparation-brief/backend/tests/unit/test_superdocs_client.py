"""Unit tests for SuperDocs pending-change normalization — no live API key."""

import json

from app.services.superdocs.client import normalize_pending_changes


def test_normalize_list_of_dicts():
    raw = [{"change_id": "c1", "operation": "replace", "ai_explanation": "Fix heading"}]
    assert normalize_pending_changes(raw)[0]["change_id"] == "c1"


def test_normalize_json_encoded_string():
    inner = [{"change_id": "c2", "ai_explanation": "Tighten wording"}]
    assert normalize_pending_changes(json.dumps(inner))[0]["change_id"] == "c2"


def test_normalize_double_encoded_content_field():
    raw = [
        {
            "change_id": "c3",
            "content": json.dumps({"html": "<p>Hi</p>"}),
        }
    ]
    out = normalize_pending_changes(raw)
    assert out[0]["content"]["html"] == "<p>Hi</p>"


def test_normalize_empty():
    assert normalize_pending_changes(None) == []
    assert normalize_pending_changes("") == []
    assert normalize_pending_changes("not-json") == []
