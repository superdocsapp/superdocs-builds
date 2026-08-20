"""The failure path is the build, not an afterthought.

Four things are asserted here and each of them is a thing we watched a product
get wrong on 2026-08-07 and again on 2026-08-09: the queue halts, the downstream
steps do not run, no export is produced, and the sentence at the end is computed
from what actually happened.
"""

from __future__ import annotations

import pytest
from simulator import Behaviour, SimulatedSuperDocs
from statutory.editplan import build_plan
from statutory.errors import DecisionAlreadyRecordedError
from statutory.orchestrator import Orchestrator
from statutory.superdocs.client import SuperDocsClient
from statutory.superdocs.decisions import DecisionLedger


def _run(rolled, behaviour: Behaviour, steps: int = 4, ledger: DecisionLedger | None = None):
    plan = build_plan(rolled.document).sample(steps)
    product = SimulatedSuperDocs(behaviour)
    client = SuperDocsClient(product, poll_seconds=0)
    ledger = ledger or DecisionLedger()
    orchestrator = Orchestrator(client, ledger, "K. Latha (CFO)", sleep=lambda _: None)
    result = orchestrator.run("run-1", plan, "statements.html")
    return result, product, ledger, orchestrator


def test_a_clean_run_applies_every_step_and_exports(rolled) -> None:
    result, product, ledger, _ = _run(rolled, Behaviour())
    assert result.ok
    assert result.applied == 4
    assert product.exports == ["docx"]
    assert ledger.accepted("run-1") == 4
    assert "4 of 4 planned change(s) verified applied" in result.sentence(ledger)
    assert "decided by K. Latha (CFO)" in result.sentence(ledger)


def test_a_failure_halts_the_queue_and_downstream_steps_never_run(rolled) -> None:
    result, product, _ledger, orchestrator = _run(rolled, Behaviour(not_applied={2, 3}))
    assert not result.ok
    assert result.halted_at == 2
    assert result.applied == 1, "step 1 landed; 3 and 4 were never attempted"
    assert product.step_index == 3, "step 2 plus its one narrow retry, and nothing after"
    assert any("halting" in line for line in orchestrator.log)


def test_no_export_after_a_failure(rolled) -> None:
    result, product, ledger, _ = _run(rolled, Behaviour(not_applied={2, 3}))
    assert product.exports == []
    assert result.exported == []
    assert "No export was produced" in result.sentence(ledger)
    assert "HALTED at step 2" in result.sentence(ledger)


def test_at_most_one_narrow_retry_and_never_a_replan(rolled) -> None:
    """The retry is the same instruction. A second failure ends it."""
    result, product, _, orchestrator = _run(rolled, Behaviour(not_applied={2, 3}))
    assert product.step_index == 3, "the step, its one retry, and nothing more"
    assert result.outcomes[-1].retried
    assert sum("narrow retry" in line for line in orchestrator.log) == 1

    messages = [line for line in orchestrator.log if "retry" in line]
    assert all("no re-plan" in line for line in messages)


def test_a_retry_that_succeeds_lets_the_run_continue(rolled) -> None:
    """One failure, one retry of the same instruction, and the run carries on."""
    result, product, ledger, _orchestrator = _run(rolled, Behaviour(not_applied={2}), steps=3)
    assert result.ok
    assert product.step_index == 4, "three steps plus one retry"
    assert [o.retried for o in result.outcomes] == [False, True, False]
    rows = ledger.decided("run-1")
    assert len(rows) == 3
    assert any(r.supersedes for r in ledger.rows), "the retry supersedes; both rows are kept"
    assert len(ledger.rows) == 4


def test_collateral_damage_is_never_retried(rolled) -> None:
    """The document already holds content nobody asked for; another turn is worse."""
    result, product, _, orchestrator = _run(rolled, Behaviour(collateral={1}))
    assert result.halted_at == 1
    assert product.step_index == 1, "no retry at all"
    assert any("collateral" in line.lower() for line in orchestrator.log)


def test_a_failed_run_reverts_and_says_whether_the_revert_worked(rolled) -> None:
    result, product, _, _ = _run(rolled, Behaviour(not_applied={1, 2}))
    assert product.reverts == 1
    assert "reverted to the last verified-good state, confirmed by read-back" in result.reverted

    result2, product2, _, _ = _run(rolled, Behaviour(not_applied={1, 2}, revert_works=False))
    assert "does NOT match the last verified-good state" in result2.reverted
    assert product2.exports == []


def test_an_upload_that_is_not_verbatim_stops_before_any_edit(rolled) -> None:
    with pytest.raises(AssertionError, match="was not verbatim"):
        _run(rolled, Behaviour(fail_upload_verbatim=True))


def test_the_decision_row_is_written_before_the_actuator_is_called(rolled) -> None:
    """Decision 33: the product's gate is write-only, so the record has to be ours.

    Asserted on one shared timeline rather than on two counts, because two counts
    that happen to be equal say nothing about the order.
    """
    plan = build_plan(rolled.document).sample(2)
    product = SimulatedSuperDocs(Behaviour())
    client = SuperDocsClient(product, poll_seconds=0)
    ledger = DecisionLedger()
    original = ledger.record

    def spy(*args, **kwargs):
        product.event_log.append("ledger-row")
        return original(*args, **kwargs)

    ledger.record = spy  # type: ignore[method-assign]
    result = Orchestrator(client, ledger, "K. Latha (CFO)", sleep=lambda _: None).run(
        "run-1", plan, "statements.html"
    )
    assert result.ok
    timeline = [
        "ledger-row" if e == "ledger-row" else "approve"
        for e in product.event_log
        if e == "ledger-row" or e.startswith("approve:")
    ]
    assert timeline == ["ledger-row", "approve", "ledger-row", "approve"]
    assert ledger.decided("run-1")[0].at, "the row carries a timestamp and an actor"
    assert ledger.decided("run-1")[0].actor == "K. Latha (CFO)"


def test_a_second_decision_on_the_same_step_is_refused_unless_it_supersedes() -> None:
    ledger = DecisionLedger()
    ledger.record("r", 1, "c", "accept", "A", "because")
    with pytest.raises(DecisionAlreadyRecordedError, match="quietly dropped"):
        ledger.record("r", 1, "c", "reject", "B", "because")
    superseding = ledger.record("r", 1, "c", "reject", "B", "because", supersede=True)
    assert superseding.supersedes
    assert len(ledger.rows) == 2, "the superseded row is kept"
    assert ledger.accepted("r") == 0 and ledger.rejected("r") == 1


def test_the_completion_sentence_is_computed_from_the_rows_it_holds() -> None:
    ledger = DecisionLedger()
    ledger.record("r", 1, "c1", "accept", "A", "x")
    ledger.record("r", 2, "c2", "reject", "B", "y")
    sentence = ledger.describe("r", planned=5)
    assert "1 accepted, 1 rejected, 3 undecided of 5 planned" in sentence
    ledger.rows.clear()
    assert "0 accepted, 0 rejected, 5 undecided" in ledger.describe("r", planned=5)
