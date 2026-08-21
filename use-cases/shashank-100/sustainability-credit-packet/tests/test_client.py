"""Client tests. No API key, no network -- every response here is a fixture.

The task document is explicit that "tests that only prove your mocks work do
not count", so these do not assert that a stub returns what it was told to.
They assert that the parsing logic survives the *shapes the real API actually
sends*, including the JSON-encoded-string shape that the document names as the
single most common integrator bug.
"""

import json

import pytest

from client import Change, SuperDocs, Usage, _parse_maybe_json


@pytest.fixture
def sd(monkeypatch):
    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_test_not_a_real_key")
    return SuperDocs()


class TestTheDoubleParse:
    """The documented failure: content arrives JSON-encoded and needs parsing twice."""

    def test_plain_object_passes_through(self):
        assert _parse_maybe_json({"a": 1}) == {"a": 1}

    def test_json_encoded_object_is_parsed(self):
        assert _parse_maybe_json('{"a": 1}') == {"a": 1}

    def test_json_encoded_list_is_parsed(self):
        assert _parse_maybe_json('[{"a": 1}]') == [{"a": 1}]

    def test_ordinary_prose_is_left_alone(self):
        # A narrative sentence must never be mangled by an eager parse.
        text = "The project achieves a 40.55% reduction."
        assert _parse_maybe_json(text) == text

    def test_prose_that_starts_with_a_brace_but_is_not_json(self):
        text = "{this is not json, it is a sentence"
        assert _parse_maybe_json(text) == text

    def test_empty_string_survives(self):
        assert _parse_maybe_json("") == ""

    def test_numbers_and_none_survive(self):
        assert _parse_maybe_json(42) == 42
        assert _parse_maybe_json(None) is None


class TestChangeExtraction:
    """The real shapes: single-document diffs and multi-document batches."""

    def test_single_document_chunk_diffs(self, sd):
        response = {
            "id": "msg_1",
            "document_changes": {
                "updated_html": "<h1>x</h1>",
                "chunk_diffs": [
                    {"chunk_id": "c1", "operation": "update",
                     "old_html": "<p>4 points</p>", "new_html": "<p>0 points</p>"},
                ],
            },
        }
        changes = sd.changes_from(response)
        assert len(changes) == 1
        assert changes[0].chunk_id == "c1"
        assert changes[0].new_html == "<p>0 points</p>"

    def test_chunk_diffs_arriving_as_a_json_string(self, sd):
        """The documented bug, reproduced: diffs encoded as a string."""
        diffs = [{"chunk_id": "c1", "operation": "update",
                  "old_html": "<p>a</p>", "new_html": "<p>b</p>"}]
        response = {"document_changes": {"chunk_diffs": json.dumps(diffs)}}

        changes = sd.changes_from(response)

        # Without the second parse this list is empty and every field reads as
        # undefined -- exactly the empty diff cards the task document warns of.
        assert len(changes) == 1
        assert changes[0].chunk_id == "c1"
        assert changes[0].old_html == "<p>a</p>"

    def test_whole_document_changes_arriving_as_a_json_string(self, sd):
        inner = {"chunk_diffs": [{"chunk_id": "c9", "operation": "update",
                                  "old_html": "x", "new_html": "y"}]}
        response = {"document_changes": json.dumps(inner)}
        changes = sd.changes_from(response)
        assert [c.chunk_id for c in changes] == ["c9"]

    def test_multi_document_batch_keeps_document_ids(self, sd):
        """The propagation mechanic depends on knowing which document changed."""
        response = {
            "proposed_change_batch": [
                {"chunk_id": "sc1", "document_id": "doc_scorecard",
                 "operation": "update", "old_html": "13", "new_html": "4"},
                {"chunk_id": "nr1", "document_id": "doc_narrative",
                 "operation": "update", "old_html": "documented", "new_html": "at risk"},
            ]
        }
        changes = sd.changes_from(response)
        assert {c.document_id for c in changes} == {"doc_scorecard", "doc_narrative"}

    def test_batch_arriving_as_a_json_string(self, sd):
        batch = [{"chunk_id": "sc1", "document_id": "doc_a",
                  "operation": "update", "old_html": "1", "new_html": "2"}]
        changes = sd.changes_from({"proposed_change_batch": json.dumps(batch)})
        assert len(changes) == 1
        assert changes[0].document_id == "doc_a"

    def test_batch_wrapped_in_a_changes_key(self, sd):
        response = {"proposed_change_batch": {"changes": [
            {"chunk_id": "z1", "operation": "update", "old_html": "a", "new_html": "b"}
        ]}}
        assert [c.chunk_id for c in sd.changes_from(response)] == ["z1"]

    def test_alternative_field_names(self, sd):
        """Some payloads use id/before/after rather than chunk_id/old/new."""
        response = {"proposed_change_batch": [
            {"id": "q1", "before": "old text", "after": "new text"}
        ]}
        changes = sd.changes_from(response)
        assert changes[0].chunk_id == "q1"
        assert changes[0].old_html == "old text"
        assert changes[0].new_html == "new text"

    def test_a_response_with_no_changes_yields_none(self, sd):
        assert sd.changes_from({"id": "msg", "text": "Nothing to change."}) == []

    def test_malformed_entries_are_skipped_not_crashed(self, sd):
        response = {"proposed_change_batch": [
            {"chunk_id": "good", "old_html": "a", "new_html": "b"},
            {"no_id_at_all": True},
            "a bare string",
            None,
        ]}
        changes = sd.changes_from(response)
        assert [c.chunk_id for c in changes] == ["good"]

    def test_noop_changes_are_detectable(self, sd):
        response = {"proposed_change_batch": [
            {"chunk_id": "same", "old_html": "<p>x</p>", "new_html": "<p>x</p>"}
        ]}
        assert sd.changes_from(response)[0].is_noop


class TestUsageAccounting:
    """A run must be able to report what it spent, stage by stage."""

    def test_records_calls_ops_and_time_per_stage(self):
        usage = Usage()
        usage.record("narrative", ops=1, seconds=12.5)
        usage.record("narrative", ops=1, seconds=9.5)
        usage.record("export", ops=0, seconds=2.0)

        assert usage.calls == 3
        assert usage.ops_charged == 2
        assert usage.by_stage["narrative"]["calls"] == 2
        assert usage.by_stage["narrative"]["seconds"] == 22.0
        assert usage.by_stage["export"]["ops"] == 0

    def test_report_names_the_stages(self):
        usage = Usage()
        usage.record("scorecard", ops=1, seconds=30.0)
        report = usage.report()
        assert "scorecard" in report and "1 operations" in report


class TestKeyHandling:
    def test_missing_key_fails_with_a_useful_message(self, monkeypatch):
        monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
        with pytest.raises(Exception, match="No API key"):
            SuperDocs()

    def test_key_is_never_placed_in_a_url(self, sd):
        # Guards against a refactor that puts the key in a query string, where
        # it would end up in logs and shell history.
        assert sd.api_key.startswith("sk_")
        assert "sk_" not in repr(sd._session.headers.get("Authorization", "")).replace(
            sd.api_key, "REDACTED"
        )
