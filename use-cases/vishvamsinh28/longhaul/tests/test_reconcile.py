"""I4: the resume point comes from durable state alone.

The unit tests here drive :mod:`longhaul.reconcile` against a stub server so each branch
of the evidence ladder can be exercised on its own, including the ones a healthy system
almost never reaches. The integration test at the bottom proves the same property the
only way that really counts: a process that never saw the first run finishing it.
"""

from __future__ import annotations

import signal
from dataclasses import dataclass, field
from typing import Any

from longhaul import reconcile
from longhaul.client import Job, SuperDocsError
from longhaul.model import Step, sha256_text

from .conftest import Harness

TOKEN = "[longhaul:0003:abcdef123456]"
PRE_HTML = "<div>before</div>"
POST_HTML = "<div>after</div>"


@dataclass
class StubClient:
    """Just enough server to exercise each evidence branch, and nothing more."""

    jobs: dict[str, Job] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    session_job_rows: list[dict[str, Any]] = field(default_factory=list)
    html: str = PRE_HTML
    history_raises: bool = False

    def get_job(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def session_history(self, session_id: str, *, include_document_html: bool = False):
        if self.history_raises:
            raise SuperDocsError("history unavailable", status=503)
        return {"messages": self.messages}

    def session_jobs(self, session_id: str) -> list[dict[str, Any]]:
        return self.session_job_rows

    def session_documents(self, session_id: str, *, include_html: bool = False):
        return [{"document_id": "doc_1", "html": self.html}]


def _step(**over: Any) -> Step:
    base = dict(
        run_id="r", step_index=3, step_id="s", doc_slug="d",
        instruction=f"do the thing {TOKEN}", token=TOKEN,
        pre_hash=sha256_text(PRE_HTML),
    )
    base.update(over)
    return Step(**base)


def _user_turn(content: str) -> dict[str, Any]:
    return {"turn_index": 4, "role": "user", "content": content}


# --- window W1: did the chat turn land? ----------------------------------

def test_absent_token_means_it_never_landed() -> None:
    client = StubClient(messages=[_user_turn("something else entirely")])
    verdict = reconcile.resolve_issue(client, "s1", _step(job_id=None), document_id="doc_1")
    assert verdict.outcome == reconcile.NOT_LANDED
    assert "absent from the session transcript" in verdict.evidence


def test_a_readable_job_is_adopted_not_reissued() -> None:
    job = Job("job_9", "awaiting_approval", {}, None, None)
    client = StubClient(jobs={"job_9": job})
    verdict = reconcile.resolve_issue(client, "s1", _step(job_id="job_9"), document_id="doc_1")
    assert verdict.outcome == reconcile.LANDED_RECOVERABLE
    assert verdict.job is job


def test_orphan_job_is_adopted_when_the_id_was_never_recorded() -> None:
    """The nastiest crash: the request went out, the job id never reached the ledger.

    The turn exists on the server with no local handle. Steps run one at a time under an
    exclusive lease, so a session job no other step has claimed can only be this one's.
    """
    client = StubClient(
        messages=[_user_turn(f"do the thing {TOKEN}")],
        session_job_rows=[
            {"job_id": "job_7", "status": "awaiting_approval", "job_type": "chat"}
        ],
    )
    verdict = reconcile.resolve_issue(
        client, "s1", _step(job_id=None), document_id="doc_1",
        claimed_job_ids=frozenset({"job_1", "job_2"}),
    )
    assert verdict.outcome == reconcile.LANDED_RECOVERABLE
    assert verdict.job.job_id == "job_7"
    assert "adopted unclaimed session job" in verdict.evidence


def test_two_unclaimed_jobs_is_not_enough_to_adopt_either() -> None:
    """Ambiguity is not resolved by picking one. Adopting the wrong job would attach a
    step to someone else's work, so the ladder falls through to document evidence."""
    client = StubClient(
        messages=[_user_turn(f"do the thing {TOKEN}")],
        session_job_rows=[
            {"job_id": "job_7", "status": "awaiting_approval", "job_type": "chat"},
            {"job_id": "job_8", "status": "awaiting_approval", "job_type": "chat"},
        ],
    )
    verdict = reconcile.resolve_issue(client, "s1", _step(job_id=None), document_id="doc_1")
    assert verdict.outcome == reconcile.LANDED_EXPIRED_NOOP


def test_expired_job_with_untouched_document_is_a_proven_noop() -> None:
    """The turn landed, its job is gone, and the document is byte-for-byte where it was.
    Nothing was committed, so re-issuing is provably safe — and is recorded as such."""
    client = StubClient(messages=[_user_turn(f"do the thing {TOKEN}")], html=PRE_HTML)
    verdict = reconcile.resolve_issue(
        client, "s1", _step(job_id="job_gone"), document_id="doc_1"
    )
    assert verdict.outcome == reconcile.LANDED_EXPIRED_NOOP
    assert "nothing was committed" in verdict.evidence


def test_expired_job_with_a_moved_document_halts() -> None:
    """The turn landed, the job is gone, and the document has changed. Whether this
    step's edits are part of that change cannot be established, so the system stops."""
    client = StubClient(messages=[_user_turn(f"do the thing {TOKEN}")], html=POST_HTML)
    verdict = reconcile.resolve_issue(
        client, "s1", _step(job_id="job_gone"), document_id="doc_1"
    )
    assert verdict.outcome == reconcile.INCONCLUSIVE
    assert not verdict.is_conclusive


def test_unreadable_history_is_inconclusive_never_a_guess() -> None:
    client = StubClient(history_raises=True)
    verdict = reconcile.resolve_issue(client, "s1", _step(job_id=None), document_id="doc_1")
    assert verdict.outcome == reconcile.INCONCLUSIVE


# --- window W2: did the approve land? -------------------------------------

def test_completed_job_means_the_approve_committed() -> None:
    client = StubClient(jobs={"j": Job("j", "completed", {}, {"response": "ok"}, None)})
    verdict = reconcile.resolve_commit(client, "s1", _step(job_id="j"), document_id="doc_1")
    assert verdict.outcome == reconcile.COMMIT_LANDED


def test_still_awaiting_means_the_approve_did_not_land() -> None:
    client = StubClient(jobs={"j": Job("j", "awaiting_approval", {}, None, None)})
    verdict = reconcile.resolve_commit(client, "s1", _step(job_id="j"), document_id="doc_1")
    assert verdict.outcome == reconcile.COMMIT_NOT_LANDED


def test_expired_approval_window_is_not_silently_reissued() -> None:
    """The proposals died with the job and the document never moved. Inventing a fresh
    turn here would commit something no human ever approved."""
    client = StubClient(html=PRE_HTML)
    verdict = reconcile.resolve_commit(client, "s1", _step(job_id="gone"), document_id="doc_1")
    assert verdict.outcome == reconcile.COMMIT_EXPIRED


# --- the property, end to end ---------------------------------------------

def test_cold_resume_uses_no_in_memory_state(harness: Harness) -> None:
    """A run finished by a process that never saw it start.

    The first process is killed mid-step with ``SIGKILL``: no unwinding, no ``finally``,
    no flush, nothing handed over. The second process is given a database path and
    nothing else, and must work out where to continue from the ledger and from what
    SuperDocs itself remembers.
    """
    trace = harness.workdir / "t.txt"
    harness.reset()
    assert harness.run(trace=trace).returncode == 0
    baseline_docs = harness.document_html()
    baseline_commits = harness.commit_log()

    checkpoints = [c for c in trace.read_text().splitlines() if c]
    midpoint = checkpoints[len(checkpoints) // 2]

    harness.reset()
    killed = harness.run(kill_at=midpoint)
    assert killed.returncode == -signal.SIGKILL

    frontier = [s for s in harness.status()["steps"]
                if s["state"] not in ("done", "rejected", "failed", "adjudicate")]
    assert frontier, "the ledger should still show unfinished work after the kill"

    resumed = harness.run()
    assert resumed.returncode == 0
    assert harness.document_html() == baseline_docs
    assert harness.commit_log() == baseline_commits
    assert "skipped as already-done" in resumed.stdout


def test_resume_reports_skipped_steps_with_their_evidence(harness: Harness) -> None:
    """A step that is not re-issued says so, and says how it knows."""
    trace = harness.workdir / "t.txt"
    harness.reset()
    assert harness.run(trace=trace).returncode == 0
    checkpoints = [c for c in trace.read_text().splitlines() if c]
    request_sent = [c for c in checkpoints if c.endswith(".request_sent")]

    harness.reset()
    assert harness.run(kill_at=request_sent[2]).returncode == -signal.SIGKILL
    resumed = harness.run()
    assert resumed.returncode == 0

    report = harness.report()
    skipped = [s for s in report["steps"] if s["disposition"].startswith("skipped")]
    assert skipped, f"nothing was reported as skipped: {report['steps']}"

    reconciled = [s for s in skipped if "reconciled" in s["disposition"]]
    assert reconciled, (
        "the step that was in flight when the process died should be reported as "
        f"reconciled, not silently re-issued: {skipped}"
    )
    # The claim must carry its evidence, or "skipped" is only an assertion.
    for step in reconciled:
        assert step["evidence"], f"step {step['step_index']} claims skipped with no evidence"
        assert "job" in step["evidence"] or "transcript" in step["evidence"]
