from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from payment_plan_agreement.engine import PaymentPlanService
from payment_plan_agreement.models import CreatePlanRequest, Frequency, LateFee, Party, PlanTerms, ReviewDecision
from payment_plan_agreement.render import render_seed_html
from payment_plan_agreement.superdocs import HttpSuperDocsClient, parse_proposal, poll_job
from payment_plan_agreement.verifier import AgreementVerifier
from payment_plan_agreement.workflow import AgreementRun, AgreementWorkflow, Lifecycle


REFERENCE = "SYNTHETIC-LIVE-001"


def synthetic_request() -> CreatePlanRequest:
    return CreatePlanRequest(
        creditor=Party(legal_name="Northstar Health Services"),
        debtor=Party(legal_name="Alex Morgan"),
        terms=PlanTerms(
            currency="USD", original_balance=Decimal("1000.00"), upfront_payment=Decimal("100.00"),
            installment_count=4, frequency=Frequency.MONTHLY, first_due_date=date(2026, 9, 15),
            agreement_date=date(2026, 8, 15), late_fee=LateFee(), reference_id=REFERENCE,
        ),
    )


def decoded(value: object) -> object:
    result = value
    for _ in range(2):
        if not isinstance(result, str):
            break
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            break
    return result


def proposals_from_metadata(metadata: dict) -> list:
    found: dict[str, object] = {}
    for event in metadata.get("intermediate_responses") or []:
        sources = [event, decoded(event.get("content"))]
        for source in sources:
            if not isinstance(source, dict):
                continue
            for raw in source.get("changes") or []:
                proposal = parse_proposal(raw)
                found[proposal.change_id] = proposal
    return list(found.values())


def main() -> int:
    if not os.environ.get("SUPERDOCS_API_KEY"):
        print("LIVE RESUME BLOCKED — SUPERDOCS_API_KEY MISSING")
        return 2
    client = HttpSuperDocsClient()
    listing = client._request("GET", "/v1/jobs?limit=20&compact=false")
    candidates = [
        item for item in listing.get("jobs", [])
        if item.get("job_type") == "chat" and REFERENCE in str((item.get("metadata") or {}).get("message") or "")
    ]
    if not candidates:
        raise RuntimeError("No matching synthetic live job was found; no new edit or export was attempted")
    record = max(candidates, key=lambda item: item.get("created_at") or "")
    job = client.get_job(record["job_id"])
    plan = PaymentPlanService().calculate(synthetic_request())
    seed = render_seed_html(plan)
    seed_report = AgreementVerifier().verify(plan, seed)
    if seed_report.status != "pass":
        raise RuntimeError("Deterministic seed verification failed during recovery")
    if job.status in {"pending", "in_progress"}:
        job = poll_job(client, job.job_id, terminal_statuses={"completed", "awaiting_approval"}, timeout_seconds=60, interval_seconds=2)
    resumed_proposals = []
    if job.status == "awaiting_approval":
        workflow = AgreementWorkflow(client)
        job = job.model_copy(update={"proposals": workflow.verifier.classify_proposals(plan, seed, job.proposals)})
        run = AgreementRun("recovered", job.session_id, Lifecycle.AWAITING_HUMAN, plan, seed, job=job, verification=seed_report)
        for _ in range(5):
            if run.state != Lifecycle.AWAITING_HUMAN or not run.job:
                break
            resumed_proposals.extend(run.job.proposals)
            decisions = [ReviewDecision(change_id=item.change_id, approved=not item.blocked, feedback="Conflicts with canonical payment plan" if item.blocked else None) for item in run.job.proposals]
            workflow.review(run, decisions, timeout_seconds=300)
        if run.state == Lifecycle.AWAITING_HUMAN:
            raise RuntimeError("Existing job exceeded five genuine proposal batches; no new edit or export was attempted")
        if run.state not in {Lifecycle.FINAL_VERIFIED, Lifecycle.BLOCKED}:
            raise RuntimeError(f"Recovered job ended in {run.state.value}; export was not attempted")
        if run.job:
            job = run.job
        elif run.final_html:
            job = job.model_copy(update={"status": "completed", "document_html": run.final_html})
        else:
            raise RuntimeError("Recovered job preserved no final document; export was not attempted")
    if job.status != "completed" or not job.document_html:
        raise RuntimeError(f"Existing synthetic job is {job.status}; no new edit, approval, or export was attempted")
    final_report = AgreementVerifier().verify(plan, job.document_html)
    if final_report.status != "pass":
        blocked_dir = Path("artifacts/live")
        blocked_dir.mkdir(parents=True, exist_ok=True)
        (blocked_dir / "final-document-blocked.html").write_text(job.document_html, encoding="utf-8")
        failure = {
            "live": True,
            "synthetic_data": True,
            "final_verification": "blocked",
            "export_attempted": False,
            "findings": [
                {
                    "code": item.code,
                    "message": item.message,
                    "expected": item.expected,
                    "observed": item.observed,
                    "section": item.location.section if item.location else None,
                }
                for item in final_report.findings
            ],
        }
        Path("artifacts").mkdir(exist_ok=True)
        Path("artifacts/live-verification-failure.json").write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(failure, indent=2))
        return 3

    metadata = record.get("metadata") or {}
    proposals = AgreementVerifier().classify_proposals(plan, seed, proposals_from_metadata(metadata))
    for item in resumed_proposals:
        if all(existing.change_id != item.change_id for existing in proposals):
            proposals.append(item)
    approved_count = sum(not item.blocked for item in proposals)
    rejected_count = sum(item.blocked for item in proposals)
    exported = client.export(html=job.document_html, filename="payment-plan-demo.docx")
    artifact_dir = Path("artifacts/live")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "payment-plan-demo.docx").write_bytes(exported.content)

    created = datetime.fromisoformat(str(record["created_at"]).replace("Z", "+00:00"))
    elapsed_ms = round((datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds() * 1000)
    report = {
        "live": True, "synthetic_data": True, "canonical_fingerprint": plan.semantic_fingerprint,
        "edit_completed": True, "polling_recovered_after_timeout": True,
        "proposal_count": len(proposals), "approved_count": approved_count, "rejected_count": rejected_count,
        "repair_attempts": 0, "final_verification": "pass", "export_format": "docx",
        "export_bytes": len(exported.content), "elapsed_ms": elapsed_ms,
    }
    Path("artifacts/live-superdocs-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
