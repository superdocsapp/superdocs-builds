"""E5 — the JSON-string trap, asserted explicitly rather than assumed."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stylefix.parsing import (  # noqa: E402
    ProposedChange,
    UnreadableProposal,
    parse_proposed_changes,
    second_parse,
)

CHANGE = {
    "change_id": "c1",
    "chunk_id": "chunk-7",
    "original": "utilizes",
    "replacement": "uses",
    "rule_id": "plain-verbs",
}


def test_object_passes_through():
    assert second_parse({"a": 1}) == {"a": 1}


def test_json_encoded_string_is_decoded():
    assert second_parse(json.dumps({"a": 1})) == {"a": 1}


def test_double_encoded_string_is_decoded():
    assert second_parse(json.dumps(json.dumps({"a": 1}))) == {"a": 1}


def test_plain_prose_is_left_alone():
    assert second_parse("uses the cache") == "uses the cache"


def test_changes_as_object_list():
    got = parse_proposed_changes({"pending_changes": [CHANGE]})
    assert got == [ProposedChange("c1", "chunk-7", "utilizes", "uses", "plain-verbs")]


def test_changes_as_json_encoded_string():
    """The documented trap: the list itself arrives as a string."""
    got = parse_proposed_changes({"pending_changes": json.dumps([CHANGE])})
    assert got[0].original == "utilizes" and got[0].replacement == "uses"


def test_each_change_individually_encoded():
    got = parse_proposed_changes({"pending_changes": [json.dumps(CHANGE)]})
    assert got[0].rule_id == "plain-verbs"


def test_nested_content_object():
    item = {"change_id": "c2", "content": json.dumps({"original": "in order to", "replacement": "to"})}
    got = parse_proposed_changes({"pending_changes": [item]})
    assert got[0].original == "in order to" and got[0].replacement == "to"


def test_wrapped_in_result_envelope():
    got = parse_proposed_changes({"result": {"changes": [CHANGE]}})
    assert got[0].change_id == "c1"


def test_unreadable_raises_rather_than_returning_empty():
    """An empty list would read as 'document is clean'. That would be a bluff."""
    with pytest.raises(UnreadableProposal):
        parse_proposed_changes({"unexpected": True})


def test_noop_change_is_flagged():
    got = parse_proposed_changes({"pending_changes": [{"original": "uses", "replacement": "uses"}]})
    assert got[0].is_noop


def test_metadata_envelope_is_read():
    """Where an async job carries the list while awaiting approval."""
    got = parse_proposed_changes(
        {"job_id": "j1", "status": "awaiting_approval",
         "metadata": {"pending_changes": [CHANGE]}}
    )
    assert got[0].change_id == "c1"


def test_explicit_null_is_no_changes_not_an_error():
    """`pending_changes: null` is a real answer: nothing pending."""
    assert parse_proposed_changes({"pending_changes": None}) == []


def test_chunk_diffs_alone_is_reported_not_read_as_proposals():
    """chunk_diffs is already-applied HTML, not proposals. Reading it as proposals
    yields empty changes that look like a clean document."""
    with pytest.raises(UnreadableProposal) as exc:
        parse_proposed_changes({"chunk_diffs": [{"chunk_id": "c1", "html": "<p>x</p>"}]})
    assert "chat_async" in str(exc.value)


def test_change_with_no_original_text_survives_as_one_bad_change():
    """One unscreenable change must not destroy the other findings for a document."""
    got = parse_proposed_changes({"pending_changes": [
        CHANGE, {"change_id": "c9", "replacement": "x"}]})
    assert len(got) == 2
    assert got[1].original == ""


def test_nested_null_is_no_changes_not_an_error():
    """The list lives in `metadata` by design, so the nested null is the one that
    matters."""
    assert parse_proposed_changes({"job_id": "j", "metadata": {"pending_changes": None}}) == []
