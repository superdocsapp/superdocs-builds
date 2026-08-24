"""The fault-injection harness.

Three scenarios, the three the task card names: network partition, duplicated
request, and process restart. Every one asserts the same thing, because there
is only one thing worth asserting — the server applied the edit exactly once.

The fake server counts its own applies, so these tests measure what actually
happened on the far side rather than what the library believes happened.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from idem import (
    Idempotent,
    OutcomeUnknown,
    Policy,
    TerminalFailure,
    UnknownPolicy,
    Verdict,
)
from tests.fakeserver import FakeServer
from tests.vectorlib import POLICY_PATH, build

PYTHON_DIR = Path(__file__).resolve().parents[1]


def _server(tmp_path):
    return FakeServer(tmp_path / "server.log")


# ---- 1. network partition ---------------------------------------------------


def test_network_partition_refuses_rather_than_double_applying(tmp_path):
    """The edit lands. The response is lost. A library that retries here
    applies it twice and bills twice."""
    server = _server(tmp_path)
    idem, _ = build(tmp_path)

    with pytest.raises(OutcomeUnknown):
        idem.run("edit-1", lambda: server.chat_async("edit-1", lose_response=True))

    assert server.applies == 1

    # Resubmitting does not wear the refusal down.
    for _ in range(5):
        with pytest.raises(OutcomeUnknown):
            idem.run("edit-1", lambda: server.chat_async("edit-1"))

    assert server.applies == 1, "the operation was applied more than once"
    assert idem.store.state_of("edit-1") == "unknown"


def test_network_partition_resolves_when_the_server_can_answer(tmp_path):
    """With a probe that can find the work the server did, the unknown outcome
    becomes a known one and the caller gets its result — still one apply.

    This is the shape the platform would make unnecessary by accepting the
    operation key itself (SPEC.md section 6)."""
    server = _server(tmp_path)
    idem, _ = build(tmp_path)

    def probe(record):
        job = server.find_by_operation_key(record.key)
        return (Verdict.APPLIED, job) if job else Verdict.NOT_APPLIED

    result = idem.run(
        "edit-2",
        lambda: server.chat_async("edit-2", lose_response=True),
        on_unknown=UnknownPolicy.RECONCILE,
        probe=probe,
    )

    assert result["status"] == "completed"
    assert server.applies == 1
    assert idem.store.state_of("edit-2") == "succeeded"


def test_network_partition_stays_refused_when_the_server_cannot_answer(tmp_path):
    """The honest case, and the common one today. The first call timed out, so
    no job id was ever bound and there is nothing to ask about. Reconciliation
    returns inconclusive and the refusal stands."""
    server = _server(tmp_path)
    idem, _ = build(tmp_path)

    with pytest.raises(OutcomeUnknown, match="inconclusive"):
        idem.run(
            "edit-3",
            lambda: server.chat_async("edit-3", lose_response=True),
            on_unknown=UnknownPolicy.RECONCILE,
        )

    assert server.applies == 1
    assert idem.reconcile("edit-3") is Verdict.INCONCLUSIVE


def test_a_conflict_after_a_partition_is_not_retried(tmp_path):
    """The production wedge, reproduced: the edit landed, the answer was lost,
    and every later call on that session conflicts. The table calls the
    conflict terminal, so the library stops instead of spending six minutes
    discovering the same thing repeatedly."""
    server = _server(tmp_path)
    idem, delays = build(tmp_path)

    with pytest.raises(OutcomeUnknown):
        idem.run("edit-4", lambda: server.chat_async("edit-4", lose_response=True))

    with pytest.raises(TerminalFailure):
        idem.run("edit-5", lambda: server.chat_async("edit-5", conflict=True))

    assert server.applies == 1
    assert delays == [], "the library backed off and retried a wedged session"
    assert idem.store.state_of("edit-5") == "failed"


# ---- 2. duplicated request --------------------------------------------------


def test_duplicated_request_sequential(tmp_path):
    server = _server(tmp_path)
    idem, _ = build(tmp_path)

    results = [idem.run("edit-6", lambda: server.chat_async("edit-6")) for _ in range(10)]

    assert server.applies == 1
    assert all(r == results[0] for r in results)


CONCURRENT_CALLERS = 20
CONCURRENT_KEYS = 60


def test_duplicated_request_concurrent(tmp_path):
    """Twenty threads contending across sixty keys. The claim is an atomic
    insert under BEGIN IMMEDIATE, so exactly one thread executes each key and
    the rest observe (R5, N6).

    Sixty keys rather than one, and a barrier per key rather than one at the
    start. Mutation testing measured why: with a single key and a single
    barrier, weakening BEGIN IMMEDIATE to BEGIN DEFERRED was detected in only
    9 of 12 trials — twenty threads get one chance to hit the window, and often
    miss it. The TypeScript harness had the same weakness and was fixed the
    same way. A test that detects a broken atomic claim three times in four is
    not a test of the atomic claim.
    """
    server = _server(tmp_path)
    idem, _ = build(tmp_path)

    outcomes: list[object] = []
    lock = threading.Lock()

    def caller(barriers):
        for n in range(CONCURRENT_KEYS):
            key = f"edit-7-{n}"
            barriers[n].wait()          # all callers arrive at each key together
            try:
                outcome = idem.run(key, lambda _k=key: server.chat_async(_k))
            except Exception as exc:    # losers are allowed to be told to wait
                outcome = exc
            with lock:
                outcomes.append(outcome)

    barriers = [threading.Barrier(CONCURRENT_CALLERS) for _ in range(CONCURRENT_KEYS)]
    threads = [threading.Thread(target=caller, args=(barriers,))
               for _ in range(CONCURRENT_CALLERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every key exactly once: never twice (a double-apply) and never zero
    # (a lost operation).
    per_key = [server.applies_for(f"edit-7-{n}") for n in range(CONCURRENT_KEYS)]
    doubled = [n for n, c in enumerate(per_key) if c > 1]
    missing = [n for n, c in enumerate(per_key) if c == 0]

    assert not doubled, f"keys applied more than once: {doubled}"
    assert not missing, f"keys never applied: {missing}"
    assert server.applies == CONCURRENT_KEYS

    unexpected = [o for o in outcomes
                  if isinstance(o, Exception) and not isinstance(o, OutcomeUnknown)]
    assert not unexpected, f"callers failed for the wrong reason: {unexpected[:3]}"


def test_duplicated_request_across_two_store_handles(tmp_path):
    """Two Idempotent instances on the same database — the shape of two workers
    on one box. The key is shared state, not instance state."""
    server = _server(tmp_path)
    policy = Policy.load(POLICY_PATH)
    a = Idempotent(tmp_path / "idem.db", policy, sleep=lambda _s: None)
    b = Idempotent(tmp_path / "idem.db", policy, sleep=lambda _s: None)

    first = a.run("edit-8", lambda: server.chat_async("edit-8"))
    second = b.run("edit-8", lambda: pytest.fail("the second handle re-executed"))

    assert first == second
    assert server.applies == 1


# ---- 3. process restart -----------------------------------------------------


def _kill_mid_flight(tmp_path, key):
    """Run a child that claims the key, sends the request, and dies holding the
    answer. Returns once it is gone."""
    proc = subprocess.run(
        [sys.executable, "tests/restart_child.py",
         str(tmp_path / "idem.db"), str(tmp_path / "server.log"), key, str(POLICY_PATH)],
        cwd=PYTHON_DIR,
        env={**os.environ, "PYTHONPATH": str(PYTHON_DIR)},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 9, f"child did not die as arranged: {proc.stderr}"


def test_process_restart(tmp_path):
    """N4. The owning process is killed between applying the edit and recording
    that it applied. A new process must not quietly do the work again."""
    server = _server(tmp_path)
    _kill_mid_flight(tmp_path, "edit-9")
    assert server.applies == 1, "the child did not apply the edit"

    # A new process, reading the record the dead one left behind.
    idem, _ = build(tmp_path)
    assert idem.store.get("edit-9").state == "in_flight"

    with pytest.raises(OutcomeUnknown):
        idem.run("edit-9", lambda: server.chat_async("edit-9"))

    assert server.applies == 1, "the restart double-applied the edit"
    assert idem.store.state_of("edit-9") == "unknown"


def test_process_restart_then_reconcile(tmp_path):
    """And having refused, the recovery path: ask the server, learn the work
    was done, return without repeating it."""
    server = _server(tmp_path)
    _kill_mid_flight(tmp_path, "edit-10")

    idem, _ = build(tmp_path)

    def probe(record):
        job = server.find_by_operation_key(record.key)
        return (Verdict.APPLIED, job) if job else Verdict.NOT_APPLIED

    result = idem.run(
        "edit-10",
        lambda: server.chat_async("edit-10"),
        on_unknown=UnknownPolicy.RECONCILE,
        probe=probe,
    )

    assert result["status"] == "completed"
    assert server.applies == 1, "reconciliation re-applied the edit"
    assert idem.store.state_of("edit-10") == "succeeded"


def test_process_restart_of_an_operation_that_never_reached_the_server(tmp_path):
    """The mirror case. The child died before the request went out, so the
    server has nothing. Reconciliation says not-applied, and only then is a
    fresh attempt justified — one apply in total, not zero and not two."""
    server = _server(tmp_path)
    idem, _ = build(tmp_path)

    # Simulate the crash directly: a claim with no attempt behind it.
    idem.store.claim("edit-11")
    with idem.store._connect() as conn:
        conn.execute("UPDATE operations SET owner_pid = 999999 WHERE key = ?", ("edit-11",))

    result = idem.run(
        "edit-11",
        lambda: server.chat_async("edit-11"),
        on_unknown=UnknownPolicy.RECONCILE,
        probe=lambda rec: (
            (Verdict.APPLIED, server.find_by_operation_key(rec.key))
            if server.find_by_operation_key(rec.key)
            else Verdict.NOT_APPLIED
        ),
    )

    assert result["status"] == "completed"
    assert server.applies == 1


# ---- 4. the Review surface: an approval that never settles -------------------
#
# The scenario that cost the most time in production, reproduced as a test.
# `approve_changes(job_id, True)` returned success, the post-approval poll never
# reached terminal, and the next call on that session 409'd — unable to proceed,
# unable to roll back. Approving twice is as wrong as editing twice, so the
# assertion here is `approvals == 1`.


def test_an_approval_whose_response_is_lost_is_not_re_approved(tmp_path):
    """The approval landed. The answer did not. Re-approving would decide the
    same proposed changes a second time."""
    server = _server(tmp_path)
    idem, _ = build(tmp_path)
    job_id = "job-review-1"

    with pytest.raises(OutcomeUnknown):
        idem.run("approve-1", lambda: server.approve("approve-1", job_id, lose_response=True))

    assert server.approvals == 1

    for _ in range(5):
        with pytest.raises(OutcomeUnknown):
            idem.run("approve-1", lambda: server.approve("approve-1", job_id))

    assert server.approvals == 1, "the approval was submitted more than once"


def test_an_approval_that_never_settles_stays_refused(tmp_path):
    """Bug 5 exactly. The approve call succeeded and the job never moved off
    `awaiting_approval`.

    A settle-shaped probe must answer INCONCLUSIVE here, not APPLIED: the
    approval was accepted, but the operation the caller cares about — the job
    reaching a terminal state — has not happened. Calling that applied would be
    the library inventing the outcome it exists to refuse.
    """
    server = _server(tmp_path)
    idem, _ = build(tmp_path)
    job_id = "job-review-2"

    def settle_probe(record):
        status = server.job_status(job_id)
        return (Verdict.APPLIED, {"job_id": job_id, "status": status}) \
            if status in ("completed", "failed", "cancelled") else Verdict.INCONCLUSIVE

    with pytest.raises(OutcomeUnknown, match="inconclusive"):
        idem.run(
            "approve-2",
            lambda: server.approve("approve-2", job_id, lose_response=True, settles=False),
            on_unknown=UnknownPolicy.RECONCILE,
            probe=settle_probe,
        )

    assert server.job_status(job_id) == "awaiting_approval"
    assert server.approvals == 1
    assert idem.store.state_of("approve-2") == "unknown"

    # And it stays refused for as long as the job stays stuck. This is the
    # difference between a library that waits for the truth and one that
    # eventually gives up and guesses.
    for _ in range(3):
        with pytest.raises(OutcomeUnknown):
            idem.run("approve-2", lambda: server.approve("approve-2", job_id),
                     on_unknown=UnknownPolicy.RECONCILE, probe=settle_probe)

    assert server.approvals == 1


def test_an_approval_that_settles_late_reconciles_without_re_approving(tmp_path):
    """The recovery path. The job was stuck, then settled on the server's own
    time. Reconciling now returns the real outcome, and the approval is never
    submitted a second time."""
    server = _server(tmp_path)
    idem, _ = build(tmp_path)
    job_id = "job-review-3"

    def settle_probe(record):
        status = server.job_status(job_id)
        return (Verdict.APPLIED, {"job_id": job_id, "status": status}) \
            if status in ("completed", "failed", "cancelled") else Verdict.INCONCLUSIVE

    with pytest.raises(OutcomeUnknown):
        idem.run("approve-3",
                 lambda: server.approve("approve-3", job_id, lose_response=True, settles=False),
                 on_unknown=UnknownPolicy.RECONCILE, probe=settle_probe)
    assert idem.reconcile("approve-3", probe=settle_probe) is Verdict.INCONCLUSIVE

    # The server settles the job — here, by a later approval arriving from
    # elsewhere, which is how it looked in production.
    server.approve("out-of-band", job_id, settles=True)
    approvals_before_recovery = server.approvals

    result = idem.run("approve-3", lambda: pytest.fail("re-approved after settling"),
                      on_unknown=UnknownPolicy.RECONCILE, probe=settle_probe)

    assert result["status"] == "completed"
    assert idem.store.state_of("approve-3") == "succeeded"
    assert server.approvals == approvals_before_recovery, "reconciliation re-approved"


def test_a_denied_proposal_is_recorded_once(tmp_path):
    """Denying is as state-changing as approving — a denial that gets replayed
    can leave the job open, which is the wedge reached from the deny path."""
    server = _server(tmp_path)
    idem, _ = build(tmp_path)

    idem.run("deny-1", lambda: server.approve("deny-1", "job-review-4", settles=True))
    for _ in range(5):
        idem.run("deny-1", lambda: pytest.fail("the denial was submitted twice"))

    assert server.approvals == 1
