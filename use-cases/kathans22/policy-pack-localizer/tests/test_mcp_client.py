"""Proves parse_proposed_changes against a real recorded response, with no network."""

from __future__ import annotations

import json
from pathlib import Path

from localizer.mcp_client import parse_proposed_changes

FIXTURE = Path(__file__).parent / "fixtures" / "proposed-change-raw.json"


def test_parses_recorded_proposed_change_fixture():
    response = json.loads(FIXTURE.read_text(encoding="utf-8"))

    changes = parse_proposed_changes(response)

    assert len(changes) == 1
    change = changes[0]
    assert change["change_id"] == "d8a679fc-60cf-4134-8a2b-85f4ed18fc2e"
    assert change["operation"] == "edit"
    assert change["chunk_id"] == "a317bb6d-04c6-45bf-b388-06c32cd2d32c"
    assert "safeguarding.in@meridian-relief.example" in change["new_html"]
    assert "Childline India" in change["new_html"]


def test_double_encoded_path_matches_already_parsed_path():
    # The fixture's metadata.pending_changes is already-an-object; the same
    # payload also lives, JSON-encoded, inside intermediate_responses. Strip
    # pending_changes so only the double-encoded path can answer, and prove
    # it produces the same edit.
    response = json.loads(FIXTURE.read_text(encoding="utf-8"))
    already_object = parse_proposed_changes(response)[0]

    response["metadata"]["pending_changes"] = None
    double_encoded = parse_proposed_changes(response)[0]

    assert double_encoded["new_html"] == already_object["new_html"]
    assert double_encoded["change_id"] == already_object["change_id"]
