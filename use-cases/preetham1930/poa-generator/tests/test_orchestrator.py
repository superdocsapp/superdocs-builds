"""The failure path is the build, not an afterthought.

Copied from `builds/statutory-statements/tests/` and rebuilt (Decision 31), plus
the three tests this build exists for. Those three are the interesting ones,
because they are the case the edit queue cannot catch on its own:

    every step succeeds, and the document is still not exportable.

A run in which six chunk replacements all verified applied and the product
quietly reworded a notice along the way is, from the queue's point of view, a
clean run. It is not one, and the gate is what says so.
"""

from __future__ import annotations

import pytest
from poa.editplan import build_plan
from poa.errors import DecisionAlreadyRecordedError
from poa.orchestrator import Orchestrator
from poa.superdocs.client import PoaClient
from poa.superdocs.decisions import DecisionLedger
from simulator import Behaviour, SimulatedSuperDocs

ACTOR = "K. Latha (reviewing paralegal)"


def _run(
    draft, library, behaviour: Behaviour, steps: int = 4, ledger: DecisionLedger | None = None
):
    plan = build_plan(draft).sample(steps)
    product = SimulatedSuperDocs(behaviour)
    client = PoaClient(product, poll_seconds=0)
    ledger = ledger or DecisionLedger()
    orchestrator = Orchestrator(client, ledger, ACTOR, library, sleep=lambda _: None)
    result = orchestrator.run("run-1", plan)
    return result, product, ledger, orchestrator


# -- the clean run --------------------------------------------------------


def test_a_clean_run_applies_every_step_and_exports(financial, library) -> None:
    result, product, ledger, _ = _run(financial, library, Behaviour())
    assert result.ok
    assert result.applied == 4
    assert product.exports == ["docx"]
    assert ledger.accepted("run-1") == 4
    sentence = result.sentence(ledger)
    assert "4 of 4 planned change(s) verified applied" in sentence
    assert "both notices were then read back verbatim before anything was exported" in sentence
    assert f"decided by {ACTOR}" in sentence


def test_the_gate_runs_on_the_upload_before_any_edit_is_issued(financial, library) -> None:
    """Nothing is gained by editing a document whose notices did not survive."""
    _result, _product, _ledger, orchestrator = _run(financial, library, Behaviour())
    gates = [line for line in orchestrator.log if line.startswith("notice gate:")]
    assert len(gates) == 2, "once after the upload, once before the export"
    assert "(after the upload)" in gates[0]
    assert "(before the export)" in gates[1]
    for line in gates:
        assert "counsel-review verbatim in chunk" in line
        assert "external-execution verbatim in chunk" in line


def test_a_notice_mangled_on_upload_stops_the_run_before_any_edit(financial, library) -> None:
    """Two independent defences stand here, and the earlier one fires first.

    `verify_upload_verbatim` compares every uploaded block against what we sent,
    so a notice reworded during ingestion is caught as a non-verbatim upload
    before the gate is even reached. Recorded as an assertion rather than left
    implicit, because a reader could reasonably expect the gate's message and
    should know why they get the other one.
    """
    product = SimulatedSuperDocs(Behaviour(corrupt_notice_on_upload="paraphrase"))
    client = PoaClient(product, poll_seconds=0)
    orchestrator = Orchestrator(client, DecisionLedger(), ACTOR, library, sleep=lambda _: None)
    with pytest.raises(AssertionError) as exc:
        orchestrator.run("run-1", build_plan(financial).sample(4))
    assert "was not verbatim" in str(exc.value)
    assert "not intended as legal advice" in str(exc.value), "the diff names the reworded notice"
    assert product.step_index == 0, "not one edit was issued"
    assert product.exports == []


# -- the case this build exists for --------------------------------------


def test_a_notice_reworded_during_a_step_is_caught_as_collateral_damage(financial, library) -> None:
    """The first of two defences, on a notice nobody targeted.

    The simulator's paraphrase is deliberately harmless-looking: 'is not legal
    advice' becomes 'is not intended as legal advice'. It reads better and means
    less, which is the shape a rewrite actually takes. The step's own change
    lands correctly - it is the notice next door that moved.
    """
    result, product, ledger, _ = _run(financial, library, Behaviour(paraphrase_notice={3}))
    assert result.halted_at == 3
    assert any("reworded-a-notice" in e for e in product.event_log)
    kinds = {p.kind for p in result.outcomes[-1].verification.problems}
    assert kinds == {"collateral_damage"}
    assert product.exports == [], "no export, and the export path was never reached"
    assert "HALTED at step 3" in result.sentence(ledger)


def test_a_reworded_notice_that_the_collateral_check_cannot_see_still_refuses_the_export(
    financial, library
) -> None:
    """The gate standing on its own.

    Drive the paraphrase on the *last* step of the plan, then read back and gate.
    Whatever the per-step verifier concluded, the document is not exportable and
    the run says which notice and how it differs.
    """
    plan = build_plan(financial)
    product = SimulatedSuperDocs(Behaviour())
    client = PoaClient(product, poll_seconds=0)
    ledger = DecisionLedger()
    orchestrator = Orchestrator(client, ledger, ACTOR, library, sleep=lambda _: None)

    original_export = client.export
    seen: list[str] = []

    def spy(*args, **kwargs):
        seen.append("export")
        return original_export(*args, **kwargs)

    client.export = spy  # type: ignore[method-assign]
    # Reword a notice after the last edit lands but before the final read-back.
    original_read_back = client.read_back
    calls = {"n": 0}

    def read_back(document_id, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2 + 2 * len(plan):  # the final read-back before the gate
            product._touch_notice("paraphrase")
        return original_read_back(document_id, **kwargs)

    client.read_back = read_back  # type: ignore[method-assign]
    result = orchestrator.run("run-1", plan)

    assert result.applied == len(plan), "every edit verified applied"
    assert result.halted_at is None, "the queue never halted"
    assert seen == [], "the export was never called"
    assert product.exports == []
    assert not result.ok
    assert "counsel-review" in result.notice_refusal
    assert "NOT exportable" in result.sentence(ledger)
    assert any("NOTICE GATE REFUSED before the export" in line for line in orchestrator.log)


def test_a_deleted_notice_refuses_the_export_too(financial, library) -> None:
    """A deleted notice removes a chunk, so the chunk set changed - also collateral."""
    result, product, ledger, _ = _run(financial, library, Behaviour(drop_notice={2}))
    assert result.halted_at == 2
    assert product.exports == []
    detail = " ".join(p.detail for p in result.outcomes[-1].verification.problems)
    assert "the chunk set changed" in detail
    assert "No export was produced" in result.sentence(ledger)


# -- the three failure classes, unchanged --------------------------------


def test_a_failure_halts_the_queue_and_downstream_steps_never_run(financial, library) -> None:
    result, product, _ledger, orchestrator = _run(financial, library, Behaviour(not_applied={2, 3}))
    assert not result.ok
    assert result.halted_at == 2
    assert result.applied == 1, "step 1 landed; 3 and 4 were never attempted"
    assert product.step_index == 3, "step 2 plus its one narrow retry, and nothing after"
    assert any("halting" in line for line in orchestrator.log)


def test_no_export_after_a_failure(financial, library) -> None:
    result, product, ledger, _ = _run(financial, library, Behaviour(not_applied={2, 3}))
    assert product.exports == []
    assert result.exported == []
    assert "No export was produced" in result.sentence(ledger)
    assert "HALTED at step 2" in result.sentence(ledger)


def test_at_most_one_narrow_retry_and_never_a_replan(financial, library) -> None:
    result, product, _, orchestrator = _run(financial, library, Behaviour(not_applied={2, 3}))
    assert product.step_index == 3, "the step, its one retry, and nothing more"
    assert result.outcomes[-1].retried
    assert sum("narrow retry" in line for line in orchestrator.log) == 1
    assert all("no re-plan" in line for line in orchestrator.log if "retry" in line)


def test_a_retry_that_succeeds_lets_the_run_continue(financial, library) -> None:
    result, product, ledger, _ = _run(financial, library, Behaviour(not_applied={2}), steps=3)
    assert result.ok
    assert product.step_index == 4, "three steps plus one retry"
    assert [o.retried for o in result.outcomes] == [False, True, False]
    assert len(ledger.decided("run-1")) == 3
    assert any(r.supersedes for r in ledger.rows), "the retry supersedes; both rows are kept"
    assert len(ledger.rows) == 4


def test_collateral_damage_is_never_retried(financial, library) -> None:
    result, product, _, orchestrator = _run(financial, library, Behaviour(collateral={1}))
    assert result.halted_at == 1
    assert product.step_index == 1, "no retry at all"
    assert any("collateral" in line.lower() for line in orchestrator.log)


def test_applied_wrong_is_detected_and_halts(financial, library) -> None:
    result, product, _, _ = _run(financial, library, Behaviour(applied_wrong={1, 2}))
    assert result.halted_at == 1
    assert product.exports == []
    kinds = {p.kind for p in result.outcomes[-1].verification.problems}
    assert kinds == {"applied_wrong"}


def test_a_failed_run_reverts_and_says_whether_the_revert_worked(financial, library) -> None:
    result, product, _, _ = _run(financial, library, Behaviour(not_applied={1, 2}))
    assert product.reverts == 1
    assert "reverted to the last verified-good state, confirmed by read-back" in result.reverted

    result2, product2, _, _ = _run(
        financial, library, Behaviour(not_applied={1, 2}, revert_works=False)
    )
    assert "does NOT match the last verified-good state" in result2.reverted
    assert product2.exports == []


def test_an_upload_that_is_not_verbatim_stops_before_any_edit(financial, library) -> None:
    with pytest.raises(AssertionError, match="was not verbatim"):
        _run(financial, library, Behaviour(fail_upload_verbatim=True))


# -- the decision ledger --------------------------------------------------


def test_the_decision_row_is_written_before_the_actuator_is_called(financial, library) -> None:
    """Decision 33: the product's gate is write-only, so the record has to be ours."""
    plan = build_plan(financial).sample(2)
    product = SimulatedSuperDocs(Behaviour())
    client = PoaClient(product, poll_seconds=0)
    ledger = DecisionLedger()
    original = ledger.record

    def spy(*args, **kwargs):
        product.event_log.append("ledger-row")
        return original(*args, **kwargs)

    ledger.record = spy  # type: ignore[method-assign]
    result = Orchestrator(client, ledger, ACTOR, library, sleep=lambda _: None).run("run-1", plan)
    assert result.ok
    timeline = [
        "ledger-row" if e == "ledger-row" else "approve"
        for e in product.event_log
        if e == "ledger-row" or e.startswith("approve:")
    ]
    assert timeline == ["ledger-row", "approve", "ledger-row", "approve"]
    assert ledger.decided("run-1")[0].at, "the row carries a timestamp and an actor"
    assert ledger.decided("run-1")[0].actor == ACTOR


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
    assert "1 accepted, 1 rejected, 3 undecided of 5 planned" in ledger.describe("r", planned=5)
    ledger.rows.clear()
    assert "0 accepted, 0 rejected, 5 undecided" in ledger.describe("r", planned=5)
