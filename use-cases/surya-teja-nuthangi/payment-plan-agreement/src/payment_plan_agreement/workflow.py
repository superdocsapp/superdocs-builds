from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

from .engine import PaymentPlanService
from .models import CreatePlanRequest, PaymentPlan, ReviewDecision
from .render import protected_instruction, render_seed_html
from .superdocs import EditJob, ExportedDocument, SuperDocsClient, poll_job
from .verifier import AgreementVerifier, VerificationReport


class Lifecycle(str, Enum):
    DRAFT="draft"; PLAN_CALCULATED="plan_calculated"; DOCUMENT_READY="document_ready"; SUBMITTING="submitting_to_superdocs"; PROCESSING="superdocs_processing"; AWAITING_HUMAN="awaiting_human"; APPLYING_APPROVALS="applying_approvals"; FINAL_VERIFIED="final_verified"; EXPORTED="exported"; BLOCKED="blocked"


@dataclass
class AgreementRun:
    run_id: str
    session_id: str
    state: Lifecycle
    plan: PaymentPlan
    seed_html: str
    job: EditJob | None = None
    final_html: str | None = None
    verification: VerificationReport | None = None
    decisions: list[ReviewDecision] = field(default_factory=list)


class AgreementWorkflow:
    def __init__(self, client: SuperDocsClient) -> None:
        self.client, self.engine, self.verifier = client, PaymentPlanService(), AgreementVerifier()

    def start(self, request: CreatePlanRequest) -> AgreementRun:
        plan = self.engine.calculate(request); seed = render_seed_html(plan)
        report = self.verifier.verify(plan, seed)
        if report.status == "blocked": raise ValueError("deterministic seed failed verification; no external request was made")
        run_id, session_id = "agr_" + uuid.uuid4().hex, "session_" + uuid.uuid4().hex
        job = self.client.start_edit(session_id, seed, protected_instruction(plan))
        state = Lifecycle.AWAITING_HUMAN if job.status == "awaiting_approval" else Lifecycle.PROCESSING
        run = AgreementRun(run_id, session_id, state, plan, seed, job=job, verification=report)
        if state == Lifecycle.AWAITING_HUMAN:
            run.job = job.model_copy(update={"proposals": self.verifier.classify_proposals(plan, seed, job.proposals)})
        return run

    def wait_for_review(self, run: AgreementRun, *, timeout_seconds: float = 180, interval_seconds: float = 2) -> AgreementRun:
        if not run.job: raise ValueError("run has no SuperDocs job")
        job = poll_job(self.client, run.job.job_id, terminal_statuses={"awaiting_approval", "completed"}, timeout_seconds=timeout_seconds, interval_seconds=interval_seconds)
        run.job = job
        if job.status == "awaiting_approval":
            run.job = job.model_copy(update={"proposals": self.verifier.classify_proposals(run.plan, run.seed_html, job.proposals)})
            run.state = Lifecycle.AWAITING_HUMAN
        elif job.document_html:
            self._finalize(run, job, [])
        else:
            raise ValueError("SuperDocs completed without final document; seed and job id are preserved")
        return run

    def review(self, run: AgreementRun, decisions: list[ReviewDecision]) -> AgreementRun:
        if run.state != Lifecycle.AWAITING_HUMAN or not run.job: raise ValueError("run is not awaiting human review")
        ids = {x.change_id for x in run.job.proposals}
        if {x.change_id for x in decisions} != ids: raise ValueError("every proposal requires one explicit item-level decision")
        blocked_ids = {x.change_id for x in run.job.proposals if x.blocked}
        wrongly_approved = blocked_ids & {x.change_id for x in decisions if x.approved}
        if wrongly_approved: raise ValueError("protected-fact changes cannot be approved; reject the blocked proposals")
        run.state = Lifecycle.APPLYING_APPROVALS
        completed = self.client.approve(run.session_id, run.job.job_id, decisions)
        if completed.status != "completed":
            completed = poll_job(self.client, run.job.job_id, terminal_statuses={"completed"}, timeout_seconds=180, interval_seconds=2)
        if not completed.document_html: raise ValueError("approval completed without final document; work is preserved")
        self._finalize(run, completed, decisions)
        return run

    def _finalize(self, run: AgreementRun, completed: EditJob, decisions: list[ReviewDecision]) -> None:
        report = self.verifier.verify(run.plan, completed.document_html)
        run.job, run.decisions, run.final_html, run.verification = completed, decisions, completed.document_html, report
        run.state = Lifecycle.BLOCKED if report.status == "blocked" else Lifecycle.FINAL_VERIFIED

    def export(self, run: AgreementRun) -> ExportedDocument:
        if run.state != Lifecycle.FINAL_VERIFIED or not run.final_html: raise ValueError("export is blocked until final verification passes")
        exported = self.client.export(html=run.final_html, filename=f"payment-plan-{run.run_id}.docx")
        run.state = Lifecycle.EXPORTED
        return exported
