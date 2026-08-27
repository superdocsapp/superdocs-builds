"""One instruction, several rounds of review.

A model can apply what was approved and then propose the next part of the same edit. The
live API does this for "add a section titled X containing Y": the heading comes back in
one round and its paragraph in the next.

A runner that assumes a single round approves the first half and then waits forever on a
job that is patiently asking about the second. That is what happened on the first live
run of this project, and these tests exist so it cannot happen again.
"""

from __future__ import annotations

import signal
import sqlite3

from .conftest import Harness


def _rounds_for(harness: Harness, step_index: int) -> int:
    conn = sqlite3.connect(str(harness.state_dir / "longhaul.db"))
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM events WHERE run_id=? AND step_index=? "
            "AND kind='review.another_round'",
            (harness.run_id, step_index),
        ).fetchone()[0]
    finally:
        conn.close()


def _create_step(harness: Harness) -> int:
    for step in harness.status()["steps"]:
        if step["id"] == "add-tool-verification":
            return step["index"]
    raise AssertionError("the proof job should contain a section-creating step")


def test_a_second_round_is_reviewed_rather_than_waited_on(harness: Harness) -> None:
    harness.reset()
    result = harness.run()
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    step = _create_step(harness)
    assert _rounds_for(harness, step) >= 1, (
        "the section-creating step should have gone through more than one review round"
    )

    # Both halves of the edit are in the document, which is only true if both rounds
    # were reviewed and committed.
    text = harness.export("markdown")["oncall-rotation.md"].decode()
    assert "Verifying the paging migration" in text, "the heading is missing"
    assert "test page from Rootly" in text, "the second round's paragraph is missing"


def test_every_round_passes_through_the_gate(harness: Harness) -> None:
    """A later round is not a rubber stamp. Its changes are decided like any other."""
    harness.reset()
    assert harness.run().returncode == 0
    step = _create_step(harness)

    conn = sqlite3.connect(str(harness.state_dir / "longhaul.db"))
    try:
        proposals = conn.execute(
            "SELECT COUNT(*) FROM proposals WHERE run_id=? AND step_index=?",
            (harness.run_id, step),
        ).fetchone()[0]
        decisions = conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE run_id=? AND step_index=?",
            (harness.run_id, step),
        ).fetchone()[0]
    finally:
        conn.close()

    assert proposals >= 2, "both rounds' changes should be persisted"
    assert decisions == proposals, (
        "every proposed change, in every round, must carry a decision"
    )


def test_a_crash_between_rounds_resumes_into_the_right_round(harness: Harness) -> None:
    harness.reset()
    trace = harness.workdir / "t.txt"
    assert harness.run(trace=trace).returncode == 0
    expected_docs = harness.document_html()
    expected_commits = harness.commit_log()

    # Checkpoints from a later round carry an .rN suffix; kill inside one.
    second_round = [c for c in trace.read_text().splitlines() if ".r2" in c]
    assert second_round, "the traced run should have entered a second review round"

    harness.reset()
    killed = harness.run(kill_at=second_round[0])
    assert killed.returncode == -signal.SIGKILL

    assert harness.run().returncode == 0
    assert harness.document_html() == expected_docs
    assert harness.commit_log() == expected_commits
    assert not harness.server.stats()["duplicate_turns"]


def test_the_commit_log_has_one_row_per_change(harness: Harness) -> None:
    """A step with several review rounds sees earlier rounds' changes again on each later
    round. The audit trail must still report each change once, or "what changed and
    because of which step" becomes an overcount."""
    harness.reset()
    assert harness.run().returncode == 0

    log = harness.commit_log()
    pairs = [(step_index, change_id) for step_index, change_id, _ in log]
    duplicates = {p for p in pairs if pairs.count(p) > 1}
    assert not duplicates, f"the commit log records these more than once: {duplicates}"

    conn = sqlite3.connect(str(harness.state_dir / "longhaul.db"))
    try:
        decisions = conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE run_id=?", (harness.run_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert len(log) == decisions, (
        f"{len(log)} commit rows for {decisions} decisions; they must correspond exactly"
    )


def test_each_document_exports_as_itself(harness: Harness) -> None:
    """In a multi-document session, exports must not all come back as the focused one.

    The export endpoint takes no per-document selector, and a document_id in the payload
    is accepted and then ignored. Against a live run that produced three byte-identical
    files that all happened to be the focused document, while the real edits sat
    correctly on the server. Exports are read back per document instead.
    """
    harness.reset()
    assert harness.run().returncode == 0

    exports = harness.export("markdown")
    assert len(exports) == 3
    assert len(set(exports.values())) == 3, (
        "every document exported to identical bytes; they are all the focused document"
    )
    marker = {
        "oncall-rotation.md": "On-Call Rotation Runbook",
        "security-incident.md": "Security Incident Runbook",
        "status-page.md": "Status Page and Customer Comms Runbook",
    }
    for name, blob in exports.items():
        assert marker[name] in blob.decode(), f"{name} is not its own document"
