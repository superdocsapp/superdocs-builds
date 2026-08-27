"""The policy, the receipt and the operation ledger.

Three things an engineer described doing by hand after a run died halfway
through a batch: guessing where to restart and paying twice for the overlap,
adding the spend up from logs and abandoning it when it did not match the
account, and putting in a hard cap that only ever said "I stopped".
"""

from __future__ import annotations

import json

import pytest

from quota_aware_agent import QuotaAwareAgent, Step, SuperDocsClient
from quota_aware_agent.budget import Balance
from quota_aware_agent.idempotency import (OperationLedger, State,
                                           operation_key)
from quota_aware_agent.policy import Policy, StopReason, WhenItDoesNotFit
from quota_aware_agent.receipt import Receipt
from tests.fake import FakeSuperDocs

DOC = b"<h1>x</h1>"


def agent(fake, **kw):
    return QuotaAwareAgent(SuperDocsClient(fake, sleep=lambda s: None), **kw)


def steps(n: int, sections: int = 10) -> list[Step]:
    return [Step(f"s{i}", f"rewrite section {i}", sections) for i in range(n)]


# -- the policy -------------------------------------------------------------

def test_the_reserve_is_held_back_from_what_may_be_spent():
    p = Policy(reserve=2)
    assert p.spendable(5) == 3
    assert p.spendable(1) == 0          # never negative


def test_a_sample_bound_of_zero_is_refused_rather_than_silently_doing_nothing():
    with pytest.raises(ValueError):
        Policy(max_steps=0)
    with pytest.raises(ValueError):
        Policy(reserve=-1)


def test_a_policy_is_frozen_so_a_run_ends_under_the_policy_it_began_with():
    p = Policy(reserve=1)
    with pytest.raises(Exception):
        p.reserve = 5                                  # type: ignore[misc]
    assert p.with_(reserve=5).reserve == 5 and p.reserve == 1


def test_every_stop_reason_says_what_the_rule_was_protecting():
    """A limit whose only feedback is 'I stopped' trains the person to raise it
    until it stops firing. Each of these has to be arguable."""
    for reason in StopReason:
        if reason is StopReason.COMPLETED:
            continue          # not a rule firing; nothing to argue with
        why = reason.explain()
        assert len(why) > 40, f"{reason.value} does not explain itself"
        assert why[0].isupper() and why.rstrip().endswith(".")


def test_refusing_a_partial_run_is_a_choice_a_caller_can_make(fake_tight):
    """Some callers would rather have nothing than a subset — a document half
    updated is worse than one not updated at all."""
    a = agent(fake_tight, policy=Policy(reserve=0,
                                        when_it_does_not_fit=WhenItDoesNotFit.REFUSE))
    report = a.run("sess", "d.html", DOC, steps(4, sections=30))
    assert report.completed == []
    assert report.stop_reason is StopReason.REFUSED_PARTIAL
    assert "refuse" in report.stopped_because.lower()


def test_degrading_is_still_the_default(fake_tight):
    report = agent(fake_tight, policy=Policy(reserve=0)).run(
        "sess", "d.html", DOC, steps(4, sections=30))
    assert report.completed and report.deferred


# -- the receipt ------------------------------------------------------------

def _receipt() -> Receipt:
    r = Receipt(session_id="sess")
    r.record("s0", "edit", billable=True, ops_charged=1, ops_estimated=1,
             balance=Balance(4, authoritative=True))
    r.record("s0", "poll", billable=False, ops_charged=0,
             balance=Balance(4, authoritative=True))
    return r


def test_what_the_platform_stated_and_what_we_believed_are_never_added_together():
    r = _receipt()
    r.record("s1", "edit", billable=True, ops_charged=None, ops_estimated=2,
             balance=Balance(2, authoritative=False))
    assert r.counted == 1              # only what a usage block said
    assert r.estimated_only == 2       # kept apart, deliberately
    assert r.unreported_billable_calls == 1


def test_a_run_that_adds_up_says_so():
    rec = _receipt().reconcile(Balance(5, authoritative=True),
                               Balance(4, authoritative=True))
    assert rec.checkable and rec.agrees
    assert "agree" in rec.explanation


def test_a_run_that_does_not_add_up_names_the_gap_instead_of_hiding_it():
    """'It didn't match the number in the account, so I stopped looking.'"""
    rec = _receipt().reconcile(Balance(5, authoritative=True),
                               Balance(2, authoritative=True))
    assert rec.checkable and not rec.agrees
    assert "difference of 2" in rec.explanation
    assert "something was charged that this run did not record" in rec.explanation


def test_it_refuses_to_reconcile_two_numbers_it_inferred():
    """A reconciliation between two guesses is theatre."""
    rec = _receipt().reconcile(Balance(5, authoritative=True),
                               Balance(4, authoritative=False))
    assert not rec.checkable
    assert "inferred rather than stated" in rec.explanation


def test_the_rendered_receipt_marks_every_number_it_did_not_get_from_the_platform():
    r = _receipt()
    r.record("s1", "edit", billable=True, ops_charged=None, ops_estimated=2,
             balance=Balance(2, authoritative=False))
    text = r.render_text(Balance(5, authoritative=True),
                         Balance(2, authoritative=False))
    assert "~2" in text          # an operation we believe, not one we were told
    assert "2?" in text          # a balance we inferred
    assert "cannot be reconciled" in text


def test_a_receipt_survives_being_serialised(fake):
    report = agent(fake).run("sess", "d.html", DOC, steps(1))
    body = json.loads(report.receipt.as_json(report.balance_at_start,
                                             report.balance_at_end))
    assert body["lines"] and body["reconciliation"]["explanation"]


# -- the operation ledger ---------------------------------------------------

def test_the_key_is_over_what_the_call_does_not_over_an_id_somebody_assigned():
    a = operation_key("sess", "s0", "rewrite section 0", 10)
    assert a == operation_key("sess", "s0", " rewrite section 0 ", 10)
    assert a != operation_key("other", "s0", "rewrite section 0", 10)
    assert a != operation_key("sess", "s0", "rewrite section 0", 11)


def test_an_applied_step_is_not_repeated_and_not_billed_again(fake, tmp_path):
    """The failure this exists for: 'I got the boundary wrong. Paid for those
    twice.' SuperDocs has no idempotency on billable writes (BUG-002), so this
    is the only place it can be prevented."""
    path = tmp_path / "ops.jsonl"
    work = steps(2)

    first = agent(fake, ledger=OperationLedger(path)).run("sess", "d.html", DOC, work)
    assert len(first.completed) == 2
    spent_first = first.receipt.counted

    fake.remaining = 500
    second = agent(fake, ledger=OperationLedger(path)).run("sess", "d.html", DOC, work)
    assert second.completed == []
    assert second.already_applied == ["s0", "s1"]
    assert second.receipt.counted == 0, "the rerun was charged for work already done"
    assert spent_first > 0
    assert "not charged again" in second.plain_language()


def test_a_call_that_was_started_and_never_confirmed_is_neither_repeated_nor_forgotten(
    fake, tmp_path
):
    """The genuinely hard case. Retrying might be charged twice and might apply
    the same edit twice; skipping might leave the work undone. There is no safe
    automatic answer, so it goes to a person."""
    path = tmp_path / "ops.jsonl"
    work = steps(1)
    key = operation_key("sess", "s0", work[0].instruction, work[0].sections)
    OperationLedger(path).begin(key, session_id="sess", step_id="s0")

    report = agent(fake, ledger=OperationLedger(path)).run("sess", "d.html", DOC, work)
    assert report.needs_a_person == ["s0"]
    assert report.completed == []
    assert report.receipt.counted == 0
    said = report.plain_language()
    assert "never confirmed" in said and "check them" in said


def test_a_person_can_resolve_what_the_agent_would_not_decide(fake, tmp_path):
    path = tmp_path / "ops.jsonl"
    work = steps(1)
    key = operation_key("sess", "s0", work[0].instruction, work[0].sections)
    ledger = OperationLedger(path)
    ledger.begin(key, session_id="sess", step_id="s0")
    assert len(ledger.unresolved()) == 1

    ledger.resolve(key, applied=False, note="the document did not have the edit")
    assert ledger.unresolved() == []
    report = agent(fake, ledger=OperationLedger(path)).run("sess", "d.html", DOC, work)
    assert report.completed == ["s0"], "a failed call must be repeatable"


def test_the_ledger_is_written_before_the_call_not_after(fake, tmp_path):
    """If it were written afterwards, a process that died mid-call would leave
    no trace of a call that was charged — and the rerun would repeat it."""
    path = tmp_path / "ops.jsonl"
    work = steps(1)

    class DiesMidCall(FakeSuperDocs):
        def request(self, method, path, **kw):
            if "chat/async" in path:
                raise KeyboardInterrupt("the process was killed")
            return super().request(method, path, **kw)

    with pytest.raises(KeyboardInterrupt):
        agent(DiesMidCall(), ledger=OperationLedger(path)).run(
            "sess", "d.html", DOC, work)

    # A fresh ledger, as a new process would build it.
    assert len(OperationLedger(path).records()) == 1


def test_a_half_written_final_line_does_not_lose_the_whole_ledger(tmp_path):
    """What an interrupted run actually leaves behind."""
    path = tmp_path / "ops.jsonl"
    ledger = OperationLedger(path)
    ledger.applied("k1", ops_charged=1)
    with path.open("a") as fh:
        fh.write('{"key": "k2", "sta')

    reopened = OperationLedger(path)
    assert reopened.get("k1").state is State.APPLIED
    assert reopened.get("k2").state is State.UNKNOWN


def test_the_last_word_about_a_key_is_the_current_one(tmp_path):
    path = tmp_path / "ops.jsonl"
    ledger = OperationLedger(path)
    ledger.begin("k1")
    ledger.applied("k1", ops_charged=1)
    assert OperationLedger(path).get("k1").state is State.APPLIED


def test_only_calls_that_were_never_accepted_are_repeatable():
    ledger = OperationLedger()
    assert ledger.get("never-seen").repeatable
    assert ledger.failed("k").repeatable
    assert not ledger.begin("k2").repeatable          # in flight
    assert not ledger.applied("k3").repeatable


# -- the budget, handed back --------------------------------------------------

def test_the_agent_hands_its_remaining_allowance_back_on_every_result(fake):
    a = agent(fake)
    a.read_allowance()
    hint = a.budget_hint()
    assert hint["remaining_operations"] > 0
    assert hint["authoritative"] is True
    assert hint["spendable_on_new_edits"] == hint["remaining_operations"] - hint["reserve"]
    assert "exports are free" in hint["note"].lower()


def test_the_hint_never_presents_an_inferred_number_as_a_confirmed_one(fake):
    a = agent(fake)
    a.run("sess", "d.html", DOC, steps(1))
    hint = a.budget_hint()
    assert hint["authoritative"] in (True, False)
    if not hint["authoritative"]:
        assert "inferred" in hint["note"]


@pytest.fixture()
def fake():
    return FakeSuperDocs()


@pytest.fixture()
def fake_tight():
    f = FakeSuperDocs()
    f.remaining = 2
    return f
