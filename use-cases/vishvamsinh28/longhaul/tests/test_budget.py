"""Spend is bounded, and running out is not the same as failing.

Operations cost money and a long job is exactly the shape of thing that spends an
allowance while nobody is watching. Both bounds stop the run *before* the turn they
cannot afford, and the run stays resumable.
"""

from __future__ import annotations

import pytest

from longhaul.budget import BudgetExhausted, OperationBudget

from .conftest import Harness


class _Job:
    def __init__(self, **usage: object) -> None:
        self.result = {"usage": usage}


def test_only_billable_turns_count() -> None:
    """A turn that changed nothing, failed, or was denied is not billed, and only the
    server knows which happened. Longhaul takes its word for it."""
    budget = OperationBudget(limit=3)
    budget.record(_Job(was_billable=True, monthly_remaining=99))
    budget.record(_Job(was_billable=False, monthly_remaining=99))
    budget.record(_Job(was_billable=True, monthly_remaining=98))
    assert budget.spent == 2
    assert budget.account_remaining == 98


def test_the_run_ceiling_stops_before_the_turn_it_cannot_afford() -> None:
    budget = OperationBudget(limit=2)
    budget.check()
    budget.record(_Job(was_billable=True))
    budget.check()
    budget.record(_Job(was_billable=True))
    with pytest.raises(BudgetExhausted, match="budget of 2 operations"):
        budget.check()


def test_the_account_reserve_is_respected_even_under_the_run_ceiling() -> None:
    """Ground truth is what the server reports, not local arithmetic. If something else
    spent the allowance mid-run, the run finds out on its next turn."""
    budget = OperationBudget(limit=1000, reserve=5)
    budget.record(_Job(was_billable=True, monthly_remaining=6))
    budget.check()
    budget.record(_Job(was_billable=True, monthly_remaining=5))
    with pytest.raises(BudgetExhausted, match="reserve"):
        budget.check()


def test_an_unbounded_budget_never_blocks() -> None:
    budget = OperationBudget()
    for _ in range(50):
        budget.record(_Job(was_billable=True))
    budget.check()


def test_a_run_stopped_by_its_budget_resumes_and_repeats_nothing(harness: Harness) -> None:
    """Running out is a pause, not a failure: the run stops before the turn it cannot
    afford and finishes later without re-issuing anything."""
    harness.reset()
    capped = harness.cli(
        "run", "--spec", str(harness.spec), "--run-id", harness.run_id,
        "--gate", "policy", "--max-operations", "3",
        "--json", str(harness.report_path),
    )
    assert capped.returncode == 4, f"expected 'blocked', got {capped.returncode}"

    report = harness.report()
    assert report["status"] == "blocked"
    assert "budget" in (report["blocked_reason"] or "")
    assert report["totals"]["billable_operations"] <= 3
    spent_so_far = harness.server.stats()["chat_calls"]
    assert spent_so_far < 8, "the cap should have stopped the run short of every step"

    finished = harness.run()
    assert finished.returncode == 0
    assert harness.status()["status"] == "completed"
    assert not harness.server.stats()["duplicate_turns"], (
        "resuming after a budget stop re-issued a turn"
    )

    # And the result is the one an uncapped run produces.
    capped_docs = harness.document_html()
    harness.reset()
    assert harness.run().returncode == 0
    assert harness.document_html() == capped_docs


def test_the_report_says_what_is_left_on_the_account(harness: Harness) -> None:
    harness.reset()
    assert harness.run().returncode == 0
    remaining = harness.report()["totals"]["account_operations_remaining"]
    assert isinstance(remaining, int), "a run must be able to say what it has left to spend"
