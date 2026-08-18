"""Tests verifying defensive parsing of SuperDocs responses including double-JSON strings."""

import json
import pytest
from live_doc_agent.models import SuperDocsAPIError
from live_doc_agent.superdocs.client import SuperDocsClient


def test_parse_standard_dict_response():
    client = SuperDocsClient()
    payload = {
        "proposed_changes": [
            {
                "change_id": "c1",
                "target_section": "Deployment",
                "old_snippet": "Friday",
                "new_snippet": "Daily",
                "explanation": "Update schedule",
            }
        ]
    }
    parsed = client._parse_proposed_changes(payload)
    assert len(parsed) == 1
    assert parsed[0].change_id == "c1"
    assert parsed[0].target_section == "Deployment"
    assert parsed[0].old_snippet == "Friday"
    assert parsed[0].new_snippet == "Daily"


def test_parse_double_encoded_json_string():
    """Crucial task requirement: proposed_changes arrives as a JSON-encoded string."""
    client = SuperDocsClient()
    inner_json = json.dumps(
        {
            "changes": [
                {
                    "id": "c_double_1",
                    "section": "Incident Response",
                    "old": "30 minutes",
                    "new": "15 minutes",
                    "reason": "New SLA policy",
                }
            ]
        }
    )
    # The outer API payload where proposed_changes value is a serialized string
    outer_payload = {"proposed_changes": inner_json}

    parsed = client._parse_proposed_changes(outer_payload)
    assert len(parsed) == 1
    assert parsed[0].change_id == "c_double_1"
    assert parsed[0].target_section == "Incident Response"
    assert parsed[0].old_snippet == "30 minutes"
    assert parsed[0].new_snippet == "15 minutes"
    assert parsed[0].explanation == "New SLA policy"


def test_parse_raw_string_double_encoded():
    client = SuperDocsClient()
    raw_str = json.dumps(
        {
            "proposed_changes": json.dumps(
                [
                    {
                        "change_id": "c3",
                        "target_section": "Database",
                        "old_snippet": "PostgreSQL 14",
                        "new_snippet": "PostgreSQL 16",
                    }
                ]
            )
        }
    )
    parsed = client._parse_proposed_changes(raw_str)
    assert len(parsed) == 1
    assert parsed[0].target_section == "Database"
    assert parsed[0].new_snippet == "PostgreSQL 16"


def test_parse_empty_or_none_returns_empty_list():
    client = SuperDocsClient()
    assert client._parse_proposed_changes(None) == []
    assert client._parse_proposed_changes({}) == []
    assert client._parse_proposed_changes("") == []


def test_malformed_string_raises_error():
    client = SuperDocsClient()
    with pytest.raises(SuperDocsAPIError):
        client._parse_proposed_changes("{ invalid json string")
