"""The step machine.

Each step walks the same ladder, and every rung is a durable, fsynced ledger write:

    PLANNED -> ISSUING -> ISSUED -> PROPOSED -> GATED -> COMMITTING -> COMMITTED -> DONE

The loop below is written so that entering it with a step already part-way up the ladder
is the *normal* case, not a special one. There is no "resume path" distinct from the
first-run path — a resumed run re-enters the same code at whatever rung the ledger says
it reached. That is why a restart cannot take a different route through the system than
the run it is continuing.

Nothing is carried between attempts in memory. After a ``SIGKILL`` there is no memory
to carry, so anything the runner needs to know is either in the ledger or is asked of
SuperDocs directly (see :mod:`longhaul.reconcile`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import reconcile
from .budget import BudgetExhausted, OperationBudget
from .checkpoints import checkpoint, step_checkpoint
from .client import (
    AmbiguousRequest,
    Job,
    SessionBusy,
    SuperDocsClient,
    SuperDocsError,
    parse_changes,
)
from .gate import Gate
from .injection import Finding, scan_file
from .ledger import ConcurrentTransition, Ledger, LeaseLost, new_owner_id
from .model import (
    ADJUDICATE,
    ADJUDICATE_DISPOSITION,
    COMMITTED,
    COMMITTING,
    DONE,
    EXECUTED,
    FAILED,
    GATED,
    ISSUED,
    ISSUING,
    PLANNED,
    PROPOSED,
    REJECTED,
    RUN_BLOCKED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_RUNNING,
    SKIPPED_LEDGER,
    SKIPPED_RECONCILED,
    Commit,
    Proposal,
    Run,
    Step,
)
from .planner import JobSpec

#: Job states worth waking up for after starting a turn.
_AWAIT = frozenset({"awaiting_approval", "completed"})

#: A single instruction can need several rounds of review. Bounded so a model that keeps
#: proposing cannot loop forever.
MAX_REVIEW_ROUNDS = 12

#: Disposition for the rare, *proven* case where a landed turn committed nothing and its
#: proposals expired, so re-issuing is a no-op against document state.
REISSUED_PROVEN_NOOP = "re-issued (proven no-op)"


@dataclass
class StepOutcome:
    step_index: int
    step_id: str
    doc_slug: str
    state: str
    disposition: str
    evidence: str | None = None
    approved: int = 0
    rejected: int = 0
    duration_ms: int = 0
    billable_ops: int = 0
    error: str | None = None


@dataclass
class RunOutcome:
    run_id: str
    status: str
    steps: list[StepOutcome] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    paused_at: int | None = None
    blocked_reason: str | None = None
    wall_ms: int = 0
    account_remaining: int | None = None

    @property
    def executed(self) -> int:
        return sum(1 for s in self.steps if s.disposition == EXECUTED)

    @property
    def skipped(self) -> int:
        return sum(1 for s in self.steps if s.disposition.startswith("skipped"))


class Paused(Exception):
    """The gate has no decision yet. Not an error; the run stops cleanly and resumes later."""

    def __init__(self, step_index: int) -> None:
        super().__init__(f"awaiting a decision on step {step_index}")
        self.step_index = step_index


class Runner:
    def __init__(
        self,
        ledger: Ledger,
        client: SuperDocsClient,
        spec: JobSpec,
        gate: Gate,
        *,
        owner: str | None = None,
        lease_ttl: float = 60.0,
        max_wait: float = 900.0,
        budget: OperationBudget | None = None,
    ) -> None:
        self.ledger = ledger
        self.client = client
        self.spec = spec
        self.gate = gate
        self.owner = owner or new_owner_id()
        self.lease_ttl = lease_ttl
        self.max_wait = max_wait
        self.budget = budget or OperationBudget()
        self._sweep = reconcile.SessionSweep.empty()

    # --- entry point ------------------------------------------------------

    def run(self, run_id: str) -> RunOutcome:
        started = time.monotonic()
        run = self.ledger.get_run(run_id)
        if run is None:
            raise SuperDocsError(f"no run {run_id}", fix="plan it first: longhaul plan <spec>")

        fence = self.ledger.acquire_lease(run_id, self.owner, self.lease_ttl)
        outcome = RunOutcome(run_id=run_id, status=RUN_RUNNING)
        self.ledger.set_run_status(run_id, RUN_RUNNING)
        try:
            outcome.findings = self._scan_sources(run)
            self._ensure_documents(run)
            self._execute_all(run, fence, outcome)
        except Paused as p:
            outcome.status = RUN_BLOCKED
            outcome.paused_at = p.step_index
            outcome.blocked_reason = f"awaiting a decision on step {p.step_index}"
            self.ledger.set_run_status(run_id, RUN_BLOCKED)
        except BudgetExhausted as exc:
            outcome.status = RUN_BLOCKED
            outcome.blocked_reason = str(exc)
            self.ledger.event(run_id, "run.budget_exhausted", str(exc))
            self.ledger.set_run_status(run_id, RUN_BLOCKED)
        except LeaseLost as exc:
            outcome.status = RUN_BLOCKED
            outcome.blocked_reason = str(exc)
            self.ledger.set_run_status(run_id, RUN_BLOCKED)
        except SuperDocsError as exc:
            outcome.status = RUN_FAILED
            outcome.blocked_reason = str(exc)
            self.ledger.event(run_id, "run.failed", str(exc))
            self.ledger.set_run_status(run_id, RUN_FAILED)
        else:
            outcome.status = self._final_status(run_id)
            self.ledger.set_run_status(run_id, outcome.status)
        finally:
            try:
                self.ledger.release_lease(run_id, self.owner, fence)
            except LeaseLost:
                pass

        outcome.wall_ms = int((time.monotonic() - started) * 1000)
        outcome.account_remaining = self.budget.account_remaining
        return outcome

    def _final_status(self, run_id: str) -> str:
        """Never report completed while a step is unresolved. I2 and I5 depend on this."""
        steps = self.ledger.get_steps(run_id)
        if any(s.state == ADJUDICATE for s in steps):
            return RUN_BLOCKED
        if any(s.state == FAILED for s in steps):
            return RUN_FAILED
        if all(s.is_terminal for s in steps):
            return RUN_COMPLETED
        return RUN_BLOCKED

    # --- sources ----------------------------------------------------------

    def _scan_sources(self, run: Run) -> list[Finding]:
        """Look for documents trying to give orders. Reported, never obeyed."""
        findings: list[Finding] = []
        for doc in self.ledger.get_documents(run.run_id):
            found = scan_file(doc.source_path, doc.slug)
            if found:
                self.ledger.event(
                    run.run_id, "injection.detected",
                    f"{doc.slug}: {len(found)} instruction-shaped passages",
                )
            findings.extend(found)
        return findings

    def _ensure_documents(self, run: Run) -> None:
        """Open every document in the session, at most once each.

        The crash window here is upload-returned-but-not-yet-bound. It is closed the same
        way as everything else: before uploading, ask the server what is already open. A
        document that was uploaded by a since-killed process is found on the roster and
        adopted rather than uploaded a second time.
        """
        for doc in self.ledger.get_documents(run.run_id):
            if doc.document_id:
                continue
            existing = self._find_on_roster(run.session_id, doc.slug)
            if existing:
                self.ledger.bind_document(run.run_id, doc.slug, existing)
                self.ledger.event(
                    run.run_id, "document.adopted",
                    f"{doc.slug} was already open as {existing}; not uploaded again",
                )
                continue
            checkpoint(f"upload.{doc.slug}.before")
            result = self.client.upload_document(
                run.session_id, Path(doc.source_path), open_mode="background"
            )
            checkpoint(f"upload.{doc.slug}.sent")
            self.ledger.bind_document(run.run_id, doc.slug, result.document_id)
            checkpoint(f"upload.{doc.slug}.bound")

    def _find_on_roster(self, session_id: str, slug: str) -> str | None:
        try:
            roster = self.client.session_documents(session_id)
        except SuperDocsError:
            return None
        for entry in roster:
            if entry.get("title") == slug:
                return entry.get("document_id")
        return None

    # --- the step loop ----------------------------------------------------

    def _execute_all(self, run: Run, fence: int, outcome: RunOutcome) -> None:
        documents = {d.slug: d for d in self.ledger.get_documents(run.run_id)}
        # Free, and done before anything else: what does the server already know?
        self._sweep = reconcile.sweep_session(self.client, run.session_id)
        if self._sweep.landed:
            self.ledger.event(
                run.run_id, "reconcile.sweep",
                f"{len(self._sweep.landed)} of this run's turns are already in the "
                f"session transcript; pending job: {self._sweep.pending_job or 'none'}",
            )
        for planned in self.ledger.get_steps(run.run_id):
            self.ledger.renew_lease(run.run_id, self.owner, fence, self.lease_ttl)
            # Reload rather than trusting the list: another process may have advanced
            # this step since the query, and the ledger is the authority.
            step = self.ledger.get_step(run.run_id, planned.step_index)
            doc = documents[step.doc_slug]

            if step.is_terminal:
                outcome.steps.append(self._describe(step, SKIPPED_LEDGER))
                continue

            try:
                result = self._execute_step(run, step, doc.document_id, fence)
            except Paused:
                raise
            except ConcurrentTransition as exc:
                # Another runner is ahead of us on this step. Backing off is correct;
                # forcing the write is how two processes issue the same edit twice.
                self.ledger.event(
                    run.run_id, "step.conceded", str(exc), step_index=step.step_index
                )
                outcome.steps.append(
                    self._describe(self.ledger.get_step(run.run_id, step.step_index),
                                   SKIPPED_LEDGER, evidence=f"conceded: {exc}")
                )
                continue
            except SuperDocsError as exc:
                self.ledger.transition(
                    run.run_id, step.step_index,
                    expect=(PLANNED, ISSUING, ISSUED, PROPOSED, GATED, COMMITTING, COMMITTED),
                    to=FAILED, error=str(exc), ended_at=time.time(),
                    disposition="failed",
                )
                outcome.steps.append(
                    self._describe(self.ledger.get_step(run.run_id, step.step_index),
                                   "failed", evidence=str(exc))
                )
                raise

            outcome.steps.append(result)

    def _execute_step(
        self, run: Run, step: Step, document_id: str | None, fence: int
    ) -> StepOutcome:
        idx = step.step_index
        cp = lambda stage: checkpoint(step_checkpoint(idx, stage))  # noqa: E731
        disposition = EXECUTED
        evidence: str | None = None

        # --- the ledger may be behind the server ---------------------------
        # A step can read PLANNED while its turn has already been issued: the ledger was
        # lost, restored, or rolled back. Killing the process never produces this, so the
        # kill-point proof cannot catch it — but a destroyed ledger can, and re-issuing
        # here would apply the edit twice.
        if step.state == PLANNED and step.token in self._sweep.landed:
            step = self.ledger.transition(
                run.run_id, idx, expect=PLANNED, to=ISSUING, fence=fence,
                job_id=self._sweep.tokens.get(step.token),
                evidence="token found in the session transcript before issuing; the "
                         "ledger was behind the server",
            )

        # --- crash recovery, before any forward progress -------------------
        if step.state in (ISSUING, ISSUED):
            step, disposition, evidence = self._recover_issue(run, step, document_id)
            if step.state == ADJUDICATE:
                return self._describe(step, ADJUDICATE_DISPOSITION, evidence=evidence)
        elif step.state == COMMITTING:
            step, disposition, evidence = self._recover_commit(run, step, document_id)
            if step.state == ADJUDICATE:
                return self._describe(step, ADJUDICATE_DISPOSITION, evidence=evidence)

        # --- issue ---------------------------------------------------------
        if step.state == PLANNED:
            self.budget.check()
            cp("before_issue")
            pre_hash = reconcile.document_hash(self.client, run.session_id, document_id)
            step = self.ledger.transition(
                run.run_id, idx, expect=PLANNED, to=ISSUING, fence=fence,
                attempt=step.attempt + 1, pre_hash=pre_hash, started_at=time.time(),
            )
            cp("issuing_recorded")
            job_id = self._issue(run, step, document_id)
            cp("request_sent")
            step = self.ledger.transition(
                run.run_id, idx, expect=ISSUING, to=ISSUED, fence=fence, job_id=job_id
            )
            cp("issued")

        # --- collect proposals ---------------------------------------------
        if step.state == ISSUED:
            job = self.client.wait_for_job(step.job_id, until=_AWAIT, max_wait=self.max_wait)
            if job.status == "failed":
                raise SuperDocsError(
                    f"step {idx} failed on the server: {job.error}",
                    fix="inspect the step's instruction; the run resumes from here once fixed",
                )
            if job.awaiting_kind == "continue_prompt":
                raise SuperDocsError(
                    f"step {idx} paused on a large-edit continue prompt",
                    fix="this step is too large for one turn; split it in the job spec",
                )
            self.budget.record(job)
            self.ledger.put_proposals(_proposals_from(run.run_id, idx, job, document_id))
            step = self.ledger.transition(
                run.run_id, idx, expect=ISSUED, to=PROPOSED, fence=fence,
                billable_ops=_billable(job),
            )
            cp("proposed")

        # --- review rounds ---------------------------------------------------
        # One instruction can need more than one round of review: the model applies what
        # it approved, then proposes the next part of the same edit. Observed against the
        # live API, where "add a section titled X containing Y" came back as a heading in
        # one round and its paragraph in the next. A loop that assumes a single round
        # approves the first half and then waits forever for a job that is patiently
        # asking about the second.
        rounds = 0
        while step.state in (PROPOSED, GATED, COMMITTING):
            rounds += 1
            if rounds > MAX_REVIEW_ROUNDS:
                raise SuperDocsError(
                    f"step {idx} is still proposing changes after {MAX_REVIEW_ROUNDS} "
                    f"rounds of review",
                    fix="the instruction is probably too broad for one turn; split it in "
                        "the job spec",
                )
            # Round one keeps the plain checkpoint names, so the kill-point set is stable.
            rcp = cp if rounds == 1 else (lambda stage: cp(f"{stage}.r{rounds}"))

            if step.state == PROPOSED:
                proposals = self.ledger.get_proposals(run.run_id, idx)
                decided = {d.change_id for d in self.ledger.get_decisions(run.run_id, idx)}
                if proposals and not {p.change_id for p in proposals} <= decided:
                    undecided = [p for p in proposals if p.change_id not in decided]
                    decisions = self.gate.decide(run.run_id, idx, undecided)
                    if decisions is None:
                        raise Paused(idx)
                    self.ledger.put_decisions(decisions)
                step = self.ledger.transition(
                    run.run_id, idx, expect=PROPOSED, to=GATED, fence=fence
                )
                rcp("gated")

            if step.state == GATED:
                rcp("before_commit")
                step = self.ledger.transition(
                    run.run_id, idx, expect=GATED, to=COMMITTING, fence=fence
                )
                rcp("committing_recorded")
                self._commit(run, step, document_id, rcp)
                rcp("committed")

            if step.state == COMMITTING:
                step = self._settle_round(run, step, document_id, fence, rcp)

        # --- settle ----------------------------------------------------------
        if step.state == COMMITTED:
            step = self._finish(run, step, document_id, fence, disposition)
            cp("done")

        return self._describe(step, disposition, evidence=evidence)

    # --- the pieces -------------------------------------------------------

    def _issue(self, run: Run, step: Step, document_id: str | None) -> str:
        """Send the turn. On an ambiguous transport failure, ask the server what happened
        rather than retrying — a retry here is how an edit gets applied twice."""
        try:
            return self.client.chat_async(
                run.session_id, step.instruction,
                document_id=document_id,
                approval_mode="ask_every_time",
                model_tier=self.spec.model_tier,
            )
        except SessionBusy as exc:
            # Some turn on this session is still waiting on a decision. If it is ours,
            # adopt it; the sweep is re-read because the situation may have changed since
            # the run started.
            self._sweep = reconcile.sweep_session(self.client, run.session_id)
            if step.token in self._sweep.landed:
                adopted = self._sweep.tokens.get(step.token)
                if adopted:
                    self.ledger.event(
                        run.run_id, "issue.adopted_staged", adopted,
                        step_index=step.step_index,
                    )
                    return adopted
            raise SuperDocsError(
                f"step {step.step_index}: {exc}",
                fix="another turn on this session has changes staged for review. Decide "
                    "them (longhaul pending / longhaul decide) or start a fresh run.",
            ) from exc
        except AmbiguousRequest as exc:
            self.ledger.event(
                run.run_id, "issue.ambiguous", str(exc), step_index=step.step_index
            )
            verdict = reconcile.resolve_issue(
                self.client, run.session_id, step, document_id=document_id,
                claimed_job_ids=self._claimed_job_ids(run.run_id, step.step_index),
            )
            if verdict.outcome == reconcile.LANDED_RECOVERABLE and verdict.job:
                return verdict.job.job_id
            if verdict.outcome == reconcile.NOT_LANDED:
                # Provably nothing landed, so one retry is safe and is recorded as such.
                self.ledger.event(
                    run.run_id, "issue.retry_safe", verdict.evidence,
                    step_index=step.step_index,
                )
                return self.client.chat_async(
                    run.session_id, step.instruction,
                    document_id=document_id,
                    approval_mode="ask_every_time",
                    model_tier=self.spec.model_tier,
                )
            raise SuperDocsError(
                f"step {step.step_index}: {verdict.evidence}",
                fix="resolve by hand: longhaul adjudicate --run <id> --step "
                    f"{step.step_index}",
            ) from exc

    def _commit(self, run: Run, step: Step, document_id: str | None, cp: Any) -> None:
        """Send the approve and record what committed. Safe to replay."""
        proposals = self.ledger.get_proposals(run.run_id, step.step_index)
        decisions = self.ledger.get_decisions(run.run_id, step.step_index)
        by_id = {d.change_id: d for d in decisions}

        if proposals:
            self.client.approve(
                run.session_id, step.job_id,
                [(p.change_id, by_id[p.change_id].approved, by_id[p.change_id].feedback)
                 for p in proposals if p.change_id in by_id],
            )
        cp("approve_sent")
        now = time.time()
        # The commit log records every decision, approved or not. It is the audit trail
        # for "what changed, when, and because of which step", and the oracle the proof
        # suite compares between an uninterrupted run and a killed one.
        #
        # Exactly one row per (step, change_id). A step with several review rounds sees
        # earlier rounds' changes again on every later round, and an approve that is
        # replayed after a crash sees all of them — neither may add a second row, or the
        # audit trail would report one change as two.
        already = {
            c.change_id for c in self.ledger.get_commits(run.run_id)
            if c.step_index == step.step_index
        }
        self.ledger.append_commits([
            Commit(
                seq=0, run_id=run.run_id, step_index=step.step_index,
                change_id=p.change_id, approved=by_id[p.change_id].approved,
                document_id=document_id, version=None, at=now,
            )
            for p in proposals
            if p.change_id in by_id and p.change_id not in already
        ])
        cp("commits_recorded")

    def _settle_round(
        self, run: Run, step: Step, document_id: str | None, fence: int, cp: Any
    ) -> Step:
        """Wait out one review round, and decide whether another one is starting.

        A job that comes back asking about changes we have not seen is not stuck — it is
        mid-conversation. Those changes are persisted and the step drops back to
        ``PROPOSED`` so the gate sees them like any other.
        """
        idx = step.step_index
        job = self.client.wait_for_job(
            step.job_id,
            until=frozenset({"completed", "awaiting_approval"}),
            max_wait=self.max_wait,
        ) if step.job_id else None

        if job and job.status == "awaiting_approval":
            if job.awaiting_kind == "continue_prompt":
                raise SuperDocsError(
                    f"step {idx} paused on a large-edit continue prompt",
                    fix="this step is too large for one turn; split it in the job spec",
                )
            known = {p.change_id for p in self.ledger.get_proposals(run.run_id, idx)}
            fresh = [c for c in job.pending_changes() if c.get("change_id") not in known]
            if fresh:
                self.ledger.put_proposals(
                    _proposals_from(run.run_id, idx, job, document_id, only=fresh)
                )
                self.ledger.event(
                    run.run_id, "review.another_round",
                    f"{len(fresh)} further change(s) proposed for the same instruction",
                    step_index=idx,
                )
                return self.ledger.transition(
                    run.run_id, idx, expect=COMMITTING, to=PROPOSED, fence=fence
                )
            # Awaiting approval with nothing new: our approve did not take effect.
            # Replaying it is safe — it names changes that already exist.
            self.ledger.event(
                run.run_id, "review.approve_replayed",
                "job still awaiting approval with no new changes", step_index=idx,
            )
            self._commit(run, step, document_id, lambda _s: None)
            job = self.client.wait_for_job(
                step.job_id, until=frozenset({"completed"}), max_wait=self.max_wait
            )

        if job:
            # Cost is read off the job, never accumulated: the turn and every round of its
            # review are one job, so adding per round would multiply the count.
            self.budget.record(job)
        step = self.ledger.transition(
            run.run_id, idx, expect=COMMITTING, to=COMMITTED, fence=fence,
            billable_ops=max(step.billable_ops, _billable(job) if job else 0),
        )
        cp("commit_settled")
        return step

    def _finish(
        self, run: Run, step: Step, document_id: str | None, fence: int, disposition: str
    ) -> Step:
        decisions = self.ledger.get_decisions(run.run_id, step.step_index)
        proposals = self.ledger.get_proposals(run.run_id, step.step_index)
        approved = sum(1 for d in decisions if d.approved)
        # Every proposed change rejected is a real outcome with a name of its own, not a
        # failure and not a success.
        final = REJECTED if (proposals and approved == 0) else DONE
        post_hash = reconcile.document_hash(self.client, run.session_id, document_id)
        duration = int((time.time() - (step.started_at or time.time())) * 1000)
        return self.ledger.transition(
            run.run_id, step.step_index, expect=COMMITTED, to=final, fence=fence,
            post_hash=post_hash, ended_at=time.time(), duration_ms=duration,
            disposition=disposition,
        )

    # --- recovery ---------------------------------------------------------

    def _claimed_job_ids(self, run_id: str, exclude_step: int) -> frozenset[str]:
        """Job ids already spoken for by other steps of this run.

        Steps run one at a time under an exclusive lease, so any session job outside this
        set belongs to the step that was in flight when the process died.
        """
        return frozenset(
            s.job_id for s in self.ledger.get_steps(run_id)
            if s.job_id and s.step_index != exclude_step
        )

    def _recover_issue(
        self, run: Run, step: Step, document_id: str | None
    ) -> tuple[Step, str, str]:
        verdict = reconcile.resolve_issue(
            self.client, run.session_id, step, document_id=document_id,
            claimed_job_ids=self._claimed_job_ids(run.run_id, step.step_index),
        )
        self.ledger.event(
            run.run_id, f"reconcile.issue.{verdict.outcome}", verdict.evidence,
            step_index=step.step_index,
        )

        if verdict.outcome == reconcile.LANDED_RECOVERABLE and verdict.job:
            step = self.ledger.transition(
                run.run_id, step.step_index, expect=(ISSUING, ISSUED), to=ISSUED,
                job_id=verdict.job.job_id, evidence=verdict.evidence,
            )
            return step, SKIPPED_RECONCILED, verdict.evidence

        if verdict.outcome == reconcile.NOT_LANDED:
            step = self.ledger.transition(
                run.run_id, step.step_index, expect=(ISSUING, ISSUED), to=PLANNED,
                evidence=verdict.evidence,
            )
            return step, EXECUTED, verdict.evidence

        if verdict.outcome == reconcile.LANDED_EXPIRED_NOOP:
            step = self.ledger.transition(
                run.run_id, step.step_index, expect=(ISSUING, ISSUED), to=PLANNED,
                evidence=verdict.evidence,
            )
            return step, REISSUED_PROVEN_NOOP, verdict.evidence

        step = self.ledger.transition(
            run.run_id, step.step_index, expect=(ISSUING, ISSUED), to=ADJUDICATE,
            evidence=verdict.evidence, disposition=ADJUDICATE_DISPOSITION,
            ended_at=time.time(),
        )
        return step, ADJUDICATE_DISPOSITION, verdict.evidence

    def _recover_commit(
        self, run: Run, step: Step, document_id: str | None
    ) -> tuple[Step, str, str]:
        verdict = reconcile.resolve_commit(
            self.client, run.session_id, step, document_id=document_id,
            decided_change_ids=frozenset(
                d.change_id
                for d in self.ledger.get_decisions(run.run_id, step.step_index)
            ),
        )
        self.ledger.event(
            run.run_id, f"reconcile.commit.{verdict.outcome}", verdict.evidence,
            step_index=step.step_index,
        )

        if verdict.outcome == reconcile.COMMIT_LANDED:
            # The approve committed before the crash. The commit rows may or may not have
            # been written; re-deriving them from the durable decisions is idempotent
            # because the log is keyed by (step, change_id).
            self._ensure_commits_recorded(run, step, document_id)
            step = self.ledger.transition(
                run.run_id, step.step_index, expect=COMMITTING, to=COMMITTED,
                evidence=verdict.evidence,
            )
            return step, SKIPPED_RECONCILED, verdict.evidence

        if verdict.outcome == reconcile.COMMIT_LANDED_NEXT_ROUND:
            # This round committed before the crash. Record it, take the new changes on
            # board, and drop back to the gate so they are decided like any others.
            self._ensure_commits_recorded(run, step, document_id)
            known = {p.change_id for p in self.ledger.get_proposals(run.run_id, step.step_index)}
            fresh = [
                c for c in (verdict.job.pending_changes() if verdict.job else [])
                if c.get("change_id") not in known
            ]
            if fresh:
                self.ledger.put_proposals(
                    _proposals_from(run.run_id, step.step_index, verdict.job, document_id,
                                    only=fresh)
                )
            step = self.ledger.transition(
                run.run_id, step.step_index, expect=COMMITTING, to=PROPOSED,
                evidence=verdict.evidence,
            )
            return step, SKIPPED_RECONCILED, verdict.evidence

        if verdict.outcome == reconcile.COMMIT_NOT_LANDED:
            step = self.ledger.transition(
                run.run_id, step.step_index, expect=COMMITTING, to=GATED,
                evidence=verdict.evidence,
            )
            return step, EXECUTED, verdict.evidence

        step = self.ledger.transition(
            run.run_id, step.step_index, expect=COMMITTING, to=ADJUDICATE,
            evidence=verdict.evidence, disposition=ADJUDICATE_DISPOSITION,
            ended_at=time.time(),
        )
        return step, ADJUDICATE_DISPOSITION, verdict.evidence

    def _ensure_commits_recorded(
        self, run: Run, step: Step, document_id: str | None
    ) -> None:
        already = {
            c.change_id for c in self.ledger.get_commits(run.run_id)
            if c.step_index == step.step_index
        }
        decisions = self.ledger.get_decisions(run.run_id, step.step_index)
        missing = [d for d in decisions if d.change_id not in already]
        if not missing:
            return
        now = time.time()
        self.ledger.append_commits([
            Commit(seq=0, run_id=run.run_id, step_index=step.step_index,
                   change_id=d.change_id, approved=d.approved,
                   document_id=document_id, version=None, at=now)
            for d in missing
        ])

    # --- reporting --------------------------------------------------------

    def _describe(
        self, step: Step, disposition: str, *, evidence: str | None = None
    ) -> StepOutcome:
        decisions = self.ledger.get_decisions(step.run_id, step.step_index)
        return StepOutcome(
            step_index=step.step_index,
            step_id=step.step_id,
            doc_slug=step.doc_slug,
            state=step.state,
            disposition=disposition,
            evidence=evidence or step.evidence,
            approved=sum(1 for d in decisions if d.approved),
            rejected=sum(1 for d in decisions if not d.approved),
            duration_ms=step.duration_ms,
            billable_ops=step.billable_ops,
            error=step.error,
        )


def _proposals_from(
    run_id: str, step_index: int, job: Job, document_id: str | None,
    only: list[dict[str, Any]] | None = None,
) -> list[Proposal]:
    """Read proposed changes off a job, whichever shape they arrive in.

    The double-parse trap is handled in :func:`longhaul.client.parse_changes`.
    """
    raw = only if only is not None else job.pending_changes()
    if not raw and job.result:
        raw = parse_changes((job.result or {}).get("changes"))
    return [
        Proposal(
            run_id=run_id,
            step_index=step_index,
            change_id=c.get("change_id") or f"ch_missing_{i}",
            operation=c.get("operation") or "edit",
            chunk_id=c.get("chunk_id"),
            document_id=c.get("document_id") or document_id,
            old_html=c.get("old_html") or "",
            new_html=c.get("new_html") or "",
            ai_explanation=c.get("ai_explanation") or "",
        )
        for i, c in enumerate(raw)
    ]


def _billable(job: Job | None) -> int:
    if not job or not job.result:
        return 0
    usage = job.result.get("usage") or {}
    return 1 if usage.get("was_billable") else 0
