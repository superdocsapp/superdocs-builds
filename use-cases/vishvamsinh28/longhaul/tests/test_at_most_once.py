"""I1 (at-most-once) and I2 (no step is skipped).

The oracle for both is the server, never the runner. The fake counts every chat turn it
receives, keyed by the idempotency token in the instruction, and deliberately does not
deduplicate — a fake that swallowed duplicates would hide exactly the bug under test.
"""

from __future__ import annotations

import signal

import pytest

from .conftest import Harness

#: The two instants where a crash leaves a question on the wire. Everything else is
#: recoverable from the ledger alone; these are the ones that need the server's help.
DANGEROUS_STAGES = ("request_sent", "approve_sent")


def _kill_points(harness: Harness, stage: str) -> list[str]:
    trace = harness.workdir / f"trace-{stage}.txt"
    harness.reset()
    assert harness.run(trace=trace).returncode == 0
    return [c for c in trace.read_text().splitlines() if c.endswith("." + stage)]


@pytest.mark.parametrize("stage", DANGEROUS_STAGES)
def test_no_turn_is_ever_issued_twice(harness: Harness, stage: str) -> None:
    """Kill in the window where the request is out and the answer is not yet recorded.

    A blind retry here is what applies an edit twice. The runner must instead ask the
    server what happened and adopt the answer.
    """
    for checkpoint in _kill_points(harness, stage):
        harness.reset()
        killed = harness.run(kill_at=checkpoint)
        assert killed.returncode == -signal.SIGKILL, (
            f"{checkpoint}: the kill did not fire, so this trial proves nothing"
        )

        resumed = harness.run()
        assert resumed.returncode == 0, f"{checkpoint}: {resumed.stdout}\n{resumed.stderr}"

        duplicates = harness.server.stats()["duplicate_turns"]
        assert not duplicates, (
            f"{checkpoint}: the server received the same turn more than once: {duplicates}"
        )


def test_no_step_is_skipped(harness: Harness) -> None:
    """Every planned step reaches a terminal state, and the commit log covers all of them."""
    harness.reset()
    baseline_run = harness.run()
    assert baseline_run.returncode == 0
    expected_commits = harness.commit_log()
    planned = harness.status()["steps"]

    trace = harness.workdir / "t.txt"
    harness.reset()
    assert harness.run(trace=trace).returncode == 0
    checkpoints = [c for c in trace.read_text().splitlines() if c]

    # Kill at a point in the middle of the run, resume, and check nothing fell out.
    harness.reset()
    assert harness.run(kill_at=checkpoints[len(checkpoints) // 2]).returncode == -signal.SIGKILL
    assert harness.run().returncode == 0

    status = harness.status()
    assert status["status"] == "completed"
    unresolved = [s for s in status["steps"]
                  if s["state"] not in ("done", "rejected", "failed", "adjudicate")]
    assert not unresolved, f"steps left unresolved: {unresolved}"
    assert len(status["steps"]) == len(planned)
    assert harness.commit_log() == expected_commits


def test_every_turn_counted_exactly_once_in_a_clean_run(harness: Harness) -> None:
    harness.reset()
    assert harness.run().returncode == 0
    counts = harness.server.stats()["turn_counts"]
    assert counts, "the run issued no turns at all"
    assert set(counts.values()) == {1}, f"turn counts were not all 1: {counts}"


def test_a_finished_run_re_run_issues_nothing(harness: Harness) -> None:
    """Running a completed job again must cost nothing and change nothing.

    Idempotency where an operation costs money: the second invocation reports every step
    as already-done rather than paying for it twice.
    """
    harness.reset()
    assert harness.run().returncode == 0
    first_calls = harness.server.stats()["chat_calls"]
    first_documents = harness.document_html()

    second = harness.run()
    assert second.returncode == 0
    assert harness.server.stats()["chat_calls"] == first_calls, (
        "re-running a finished job issued fresh turns"
    )
    assert harness.document_html() == first_documents
    assert "skipped as already-done" in second.stdout
