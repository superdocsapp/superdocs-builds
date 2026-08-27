import pytest

from edit_precision_evaluator.approaches import (
    parse_search_chunk_ids,
    scoped_edit_prompt,
    search_prompt,
)
from edit_precision_evaluator.budget import BudgetExceeded, OperationBudget, estimated_operations
from edit_precision_evaluator.models import CorpusCase
from edit_precision_evaluator.runner import select_cases


def test_small_both_approaches_estimate_is_twelve_operations() -> None:
    assert estimated_operations(4, {"direct", "search_scoped"}) == 12


def test_budget_stops_before_exceeding_declared_cap() -> None:
    budget = OperationBudget(cap=2)
    budget.reserve()
    budget.reserve()

    with pytest.raises(BudgetExceeded):
        budget.reserve()


def test_budget_reconciles_actual_charge() -> None:
    budget = OperationBudget(cap=4)
    budget.reserve(1)
    budget.reconcile(reserved=1, actual=2)

    assert budget.used == 2
    assert budget.remaining == 2


def test_search_response_json_is_parsed_without_duplicate_ids() -> None:
    response = 'Result: {"chunk_ids":["target", "target", "second"]}'

    assert parse_search_chunk_ids(response) == ["target", "second"]


def test_invalid_search_response_falls_back_to_narrow_scope_instruction() -> None:
    assert parse_search_chunk_ids("No matching section") == []
    prompt = scoped_edit_prompt("Change one value", [])
    assert "no reliable chunk ID" in prompt
    assert "Change one value" in prompt


def test_search_prompt_contains_literal_json_contract() -> None:
    prompt = search_prompt("Change the target")

    assert '{"chunk_ids":["id"]}' in prompt
    assert "Change the target" in prompt


def test_full_run_is_blocked_until_second_review() -> None:
    pending_case = CorpusCase.model_validate(
        {
            "case_id": "pending",
            "document": "doc.html",
            "instruction": "Change target",
            "instruction_type": "single_sentence",
            "label_rationale": "Fixture",
            "labeler": "primary",
            "acceptable_scopes": [
                {
                    "scope_id": "scope",
                    "expected_change_ids": ["target"],
                    "explanation": "Fixture",
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="second-review approval"):
        select_cases([pending_case], "full")
