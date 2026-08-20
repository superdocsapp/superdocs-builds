"""SuperDocs client utilities: JSON extraction (incl. the double-encoded
second parse), usage normalization, and the budget guard ledger behavior."""

import json

import pytest

from app.budget import BudgetExceeded, BudgetGuard
from app.superdocs_client import extract_json_from_text, parse_usage


class TestExtractJson:
    def test_plain_dict(self):
        assert extract_json_from_text('{"a": 1}') == {"a": 1}

    def test_empty_object(self):
        assert extract_json_from_text("{}") == {}

    def test_json_encoded_as_string(self):
        # the second parse integrators keep missing: the API wraps JSON in a JSON string
        wrapped = json.dumps({"scores": {"faithfulness": 4}})
        assert extract_json_from_text(wrapped) == {"scores": {"faithfulness": 4}}

    def test_json_inside_fence_and_prose(self):
        text = ("Sure! Here is the result:\n```json\n{\"a\": 1, \"b\": [2]}\n```\nHope that helps.")
        assert extract_json_from_text(text) == {"a": 1, "b": [2]}

    def test_prose_with_embedded_object(self):
        assert extract_json_from_text('scoring: {"x": {"y": 2}} done') == {"x": {"y": 2}}

    def test_not_json(self):
        assert extract_json_from_text("Done.") is None
        assert extract_json_from_text("") is None
        assert extract_json_from_text(None) is None

    def test_array_is_rejected(self):
        assert extract_json_from_text("[1, 2, 3]") is None

    def test_malformed_braces(self):
        assert extract_json_from_text("{\"a\": }") is None


class TestParseUsage:
    def test_top_level_usage(self):
        assert parse_usage({"usage": {"was_billable": True, "ops_charged": 2,
                                      "monthly_remaining": 10}}) == {
            "was_billable": True, "ops_charged": 2, "monthly_remaining": 10, "monthly_used": None}

    def test_nested_quota(self):
        assert parse_usage({"quota": {"was_billable": True, "ops_charged": 1}})["ops_charged"] == 1

    def test_missing_usage_is_free(self):
        assert parse_usage({"job_id": "j1"}) == {"was_billable": False, "ops_charged": 0}

    def test_non_dict_usage(self):
        assert parse_usage({"usage": "nope"})["was_billable"] is False

    def test_billable_without_ops_charged_counts_one(self):
        # ops_charged absent but was_billable -> the guard's own fallback
        entry = parse_usage({"usage": {"was_billable": True}})
        assert entry["was_billable"] is True
        assert entry["ops_charged"] == 0


class TestBudgetGuard:
    def test_record_and_report(self, tmp_path):
        guard = BudgetGuard(cap_ops=10, ledger_path=tmp_path / "ledger.jsonl")
        guard.record({"usage": {"was_billable": True, "ops_charged": 1, "monthly_remaining": 99}},
                     endpoint="/v1/chat/async", tag="edit:x")
        guard.record({"usage": {"was_billable": False, "ops_charged": 0}}, endpoint="/export")
        report = guard.report()
        assert report["spent_ops"] == 1
        assert report["billable_calls"] == 1
        assert report["total_calls_recorded"] == 2
        assert report["remaining_within_cap"] == 9
        assert report["entries"][0]["tag"] == "edit:x"
        assert report["entries"][0]["endpoint"] == "/v1/chat/async"

    def test_guard_blocks_at_cap(self, tmp_path):
        guard = BudgetGuard(cap_ops=2, ledger_path=tmp_path / "ledger.jsonl")
        guard.record({"usage": {"was_billable": True, "ops_charged": 2}})
        with pytest.raises(BudgetExceeded):
            guard.guard(1)

    def test_guard_allows_within_cap(self, tmp_path):
        guard = BudgetGuard(cap_ops=2, ledger_path=tmp_path / "ledger.jsonl")
        guard.record({"usage": {"was_billable": True, "ops_charged": 1}})
        guard.guard(1)  # spent 1 + need 1 <= cap 2
        with pytest.raises(BudgetExceeded):
            guard.guard(2)  # spent 1 + need 2 > cap 2

    def test_spend_is_process_local(self, tmp_path):
        guard = BudgetGuard(cap_ops=10, ledger_path=tmp_path / "ledger.jsonl")
        guard.record({"usage": {"was_billable": True, "ops_charged": 1}})
        assert guard.spend_this_process() == 1
        guard2 = BudgetGuard(cap_ops=10, ledger_path=tmp_path / "ledger.jsonl")
        assert guard2.spend_this_process() == 0
        assert guard2.total_spend() == 1  # reads the ledger

    def test_persists_across_instances(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        BudgetGuard(cap_ops=10, ledger_path=ledger).record(
            {"usage": {"was_billable": True, "ops_charged": 3}})
        assert BudgetGuard(cap_ops=10, ledger_path=ledger).total_spend() == 3

    def test_billable_fallback_counts_one_op(self, tmp_path):
        guard = BudgetGuard(cap_ops=10, ledger_path=tmp_path / "ledger.jsonl")
        guard.record({"usage": {"was_billable": True}})  # no ops_charged
        assert guard.total_spend() == 1