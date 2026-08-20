"""The run: upload once, then one verified chunk replacement at a time.

The shape of a step, and every part of it is load-bearing:

    compute the expected post-state of the WHOLE document
    -> one instruction, one chunk, on the async route
    -> poll to the gate
    -> refuse anything that is not exactly our one change
    -> write OUR decision row, with an actor
    -> approve (the actuator)
    -> poll to completed
    -> read the whole document back
    -> classify: ok | not applied | applied wrong | collateral damage

On any failure the queue **halts**. No downstream step runs, because a
downstream step is the consequence of work that may not have happened - that is
the 2026-08-07 corrupted-document mechanism and the halt is the whole defence.
Then: revert to the last verified-good state, read back again to confirm the
revert actually happened, surface the diff, and produce **no export**.

Retry policy: at most one narrow retry of the same instruction, never a re-plan.
Re-planning is the degradation mode, measured twice; and a retry diffs the whole
document, because failed content has been seen arriving a turn later.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from .chunks import ChunkMap
from .editplan import Plan, bind_chunk_ids
from .superdocs.client import SuperDocsClient, select_our_change
from .superdocs.decisions import DecisionLedger
from .superdocs.verifier import Verification, verify, verify_upload_verbatim


@dataclass
class StepOutcome:
    index: int
    role: str
    verification: Verification
    retried: bool = False
    job_id: str = ""

    @property
    def ok(self) -> bool:
        return self.verification.ok


@dataclass
class RunResult:
    run_id: str
    document_id: str = ""
    session_id: str = ""
    planned: int = 0
    outcomes: list[StepOutcome] = field(default_factory=list)
    upload_receipt: str = ""
    halted_at: int | None = None
    exported: list[str] = field(default_factory=list)
    reverted: str = ""
    checklist_receipt: str = ""

    @property
    def applied(self) -> int:
        return sum(1 for o in self.outcomes if o.ok)

    @property
    def ok(self) -> bool:
        return self.halted_at is None and self.applied == self.planned

    def sentence(self, ledger: DecisionLedger) -> str:
        """Computed from the outcomes and the rows, at the moment it is emitted."""
        if self.halted_at is not None:
            return (
                f"HALTED at step {self.halted_at}. {self.applied} of {self.planned} planned "
                f"change(s) verified applied; the rest were not attempted. No export was "
                f"produced. {ledger.describe(self.run_id, self.planned)}."
            )
        return (
            f"{self.applied} of {self.planned} planned change(s) verified applied by reading "
            f"the whole document back after each one. "
            f"{ledger.describe(self.run_id, self.planned)}."
        )


class Orchestrator:
    def __init__(
        self,
        client: SuperDocsClient,
        ledger: DecisionLedger,
        actor: str,
        *,
        sleep=time.sleep,
        export_formats: tuple[str, ...] = ("docx",),
        export_dir: Path | None = None,
    ) -> None:
        self.client = client
        self.ledger = ledger
        self.actor = actor
        self.sleep = sleep
        self.export_formats = export_formats
        self.export_dir = export_dir
        self.log: list[str] = []

    def _say(self, line: str) -> None:
        self.log.append(line)

    def run(self, run_id: str, plan: Plan, filename: str) -> RunResult:
        result = RunResult(run_id=run_id, planned=len(plan))
        skeleton_blocks = [b.skeleton for b in plan.document.blocks]

        document_id, session_id = self.client.upload_verbatim(
            filename, plan.document.html("skeleton")
        )
        result.document_id, result.session_id = document_id, session_id
        uploaded, _ = self.client.read_back(document_id)
        result.upload_receipt = verify_upload_verbatim(uploaded, skeleton_blocks)
        self._say(result.upload_receipt)
        bind_chunk_ids(plan, uploaded)

        before = uploaded
        last_good = before
        for step in plan.steps:
            outcome = self._one_step(run_id, step, before, session_id, document_id)
            result.outcomes.append(outcome)
            if not outcome.ok:
                result.halted_at = step.index
                self._say(outcome.verification.report())
                self._say(
                    "halting: no downstream step runs on the consequences of an unconfirmed one"
                )
                result.reverted = self._revert(session_id, document_id, last_good, result.applied)
                return result
            self._say(outcome.verification.report())
            before, _ = self.client.read_back(document_id)
            last_good = before

        for fmt in self.export_formats:
            written = self.client.export(session_id, fmt, self.export_dir)
            result.exported.append(f"{fmt} -> {written}" if written else fmt)
        return result

    def _one_step(
        self, run_id: str, step, before: ChunkMap, session_id: str, document_id: str
    ) -> StepOutcome:
        verification = self._attempt(run_id, step, before, session_id, document_id)
        if verification.ok:
            return StepOutcome(step.index, step.role, verification)
        # One narrow retry of the same instruction. Never a re-plan: re-planning
        # is the measured degradation mode. Collateral damage is not retried at
        # all - the document already holds content nobody asked for.
        if any(p.kind == "collateral_damage" for p in verification.problems):
            return StepOutcome(step.index, step.role, verification)
        self._say(f"step {step.index}: one narrow retry, same instruction, no re-plan")
        # The retry is compared against the **last verified-good** state, not
        # against whatever the failed attempt left behind. Comparing against the
        # wreckage turns "it applied the wrong thing twice" into "it did
        # nothing", which is a different diagnosis and the wrong one. Found on
        # the first live run of this build.
        retried = self._attempt(run_id, step, before, session_id, document_id, supersede=True)
        return StepOutcome(step.index, step.role, retried, retried=True)

    def _attempt(
        self,
        run_id: str,
        step,
        before: ChunkMap,
        session_id: str,
        document_id: str,
        supersede: bool = False,
    ) -> Verification:
        job = self.client.chat_gated(session_id, document_id, step.instruction())
        if not job.awaiting:
            return Verification(
                step.index,
                step.chunk_id,
                problems=[
                    _problem(
                        "not_applied",
                        f"the job reached status {job.status!r} without ever offering a change "
                        f"to approve. Nothing was decided and nothing is claimed.",
                    )
                ],
            )
        change, unasked = select_our_change(job, step.chunk_id)
        # Our row first, then the actuator (Decision 33).
        self.ledger.record(
            run_id,
            step.index,
            step.chunk_id,
            "accept",
            self.actor,
            f"replacement for {step.role} matches the post-state computed from the ledger",
            supersede=supersede,
        )
        self.client.approve(session_id, job.job_id, change.change_id)
        for extra in unasked:
            # Denied bare: no feedback, ever (Decision 34). A rejected change
            # still gets a row with an actor, because "who decided this" has to
            # have an answer for every change the product offered, not only for
            # the ones we wanted.
            self.ledger.record(
                run_id,
                step.index,
                extra.chunk_id,
                "reject",
                self.actor,
                "not in the computed plan; the product proposed it unasked",
                supersede=True,
            )
            self.client.deny(session_id, job.job_id, extra.change_id)
            self._say(
                f"step {step.index}: denied an unasked change on chunk {extra.chunk_id} "
                f"(bare, no feedback)"
            )
        settled = self.client.poll(job.job_id, until_terminal=True, sleep=self.sleep)
        del settled  # the job's own account of itself is not evidence
        after, _ = self.client.read_back(document_id)
        return verify(step.index, step.chunk_id, before, after, step.expected_html)

    def _revert(self, session_id: str, document_id: str, last_good: ChunkMap, applied: int) -> str:
        """Revert to the last verified-good turn, then read back and say what happened."""
        try:
            self.client.revert(session_id, turn_index=applied)
        except Exception as exc:
            return f"revert call failed: {exc}. The document is left as it is and NOT exported."
        after, _ = self.client.read_back(document_id)
        same = [c.canonical for c in after.chunks] == [c.canonical for c in last_good.chunks]
        if same:
            return "reverted to the last verified-good state, confirmed by read-back"
        return (
            "revert was requested and the read-back does NOT match the last verified-good "
            f"state ({len(after)} chunk(s) now, {len(last_good)} then). The document is left "
            f"as it is, no export was produced, and this is reported rather than smoothed over."
        )


def _problem(kind: str, detail: str):
    from .superdocs.verifier import Problem

    return Problem(kind, detail)


def write_artifacts(out_dir: Path, plan: Plan) -> list[Path]:
    """The computed document, both shapes, on disk - so a reviewer can read them."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for which in ("skeleton", "target"):
        path = out_dir / f"statements-{which}.html"
        path.write_text(plan.document.html(which), encoding="utf-8")
        written.append(path)
    return written
