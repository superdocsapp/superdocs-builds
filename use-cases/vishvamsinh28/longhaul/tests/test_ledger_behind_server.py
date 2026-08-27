"""When the ledger knows less than the server.

Killing a process leaves the ledger intact, so the kill-point proof cannot reach this
case at all. But a ledger can be lost, restored from an older backup, or rolled back
while SuperDocs keeps every turn that was already issued — and then a step reads
``PLANNED`` for work that has in fact already happened.

Re-issuing there applies the edit twice. These tests exist because a live run found this:
an interrupted job left changes staged for review, the ledger was replaced, and the very
next instruction came back ``409 session_busy`` from the real API.
"""

from __future__ import annotations

import json
import signal

from .conftest import Harness


def test_a_lost_ledger_does_not_reissue_turns_the_server_already_has(
    harness: Harness,
) -> None:
    harness.reset()
    trace = harness.workdir / "t.txt"
    assert harness.run(trace=trace).returncode == 0
    expected_docs = harness.document_html()
    turns_before = harness.server.stats()["turn_counts"]
    assert set(turns_before.values()) == {1}

    # The server keeps everything; the ledger is gone.
    harness.destroy_ledger()

    resumed = harness.run()
    assert resumed.returncode == 0, f"{resumed.stdout}\n{resumed.stderr}"

    duplicates = harness.server.stats()["duplicate_turns"]
    assert not duplicates, (
        f"a lost ledger caused turns to be issued a second time: {duplicates}"
    )
    assert harness.document_html() == expected_docs, (
        "re-running against a lost ledger changed the documents"
    )

    report = harness.report()
    assert report["totals"]["executed"] == 0, (
        "every step was already on the server; none should have been executed again"
    )
    assert report["totals"]["skipped_already_done"] == len(report["steps"])
    for step in report["steps"]:
        assert "transcript" in (step["evidence"] or "") or "job" in (step["evidence"] or ""), (
            f"step {step['step_index']} skipped without naming its evidence"
        )


def test_a_session_with_changes_staged_for_review_is_not_given_a_new_instruction(
    harness: Harness,
) -> None:
    """The live API refuses this with 409 session_busy, and it is right to.

    The failure mode it prevents is real: issue a fresh turn while an earlier one is still
    awaiting a decision, and a human ends up approving changes computed against a document
    that has since moved.
    """
    harness.reset()
    blocked = harness.run(gate="deferred")
    assert blocked.returncode == 4
    pending = json.loads(
        harness.cli("pending", "--run", harness.run_id, "--json").stdout
    )
    assert pending, "the run should have staged changes awaiting a decision"
    staged_step = pending[0]["step_index"]

    # Lose the ledger while those changes are still staged. This is exactly the state a
    # live run left behind when it was interrupted mid-review.
    harness.destroy_ledger()

    recovered = harness.run(gate="policy")
    assert recovered.returncode == 0, (
        f"the run did not recover from a staged review with no ledger:\n"
        f"{recovered.stdout}\n{recovered.stderr}"
    )
    assert not harness.server.stats()["duplicate_turns"]

    report = harness.report()
    adopted = [s for s in report["steps"] if s["step_index"] == staged_step]
    assert adopted and adopted[0]["disposition"].startswith("skipped"), (
        f"the staged turn should have been adopted, not re-issued: {adopted}"
    )


def test_a_kill_plus_a_lost_ledger_still_does_not_double_apply(harness: Harness) -> None:
    """Both failures at once: the process dies and the ledger does not survive either."""
    harness.reset()
    trace = harness.workdir / "t.txt"
    assert harness.run(trace=trace).returncode == 0
    expected = harness.document_html()

    checkpoints = [c for c in trace.read_text().splitlines() if c]
    request_sent = [c for c in checkpoints if c.endswith(".request_sent")]

    harness.reset()
    assert harness.run(kill_at=request_sent[3]).returncode == -signal.SIGKILL
    harness.destroy_ledger()

    assert harness.run().returncode == 0
    assert not harness.server.stats()["duplicate_turns"]
    assert harness.document_html() == expected
