from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

from payment_plan_agreement.models import CreatePlanRequest, Frequency, LateFee, Party, PlanTerms, ReviewDecision
from payment_plan_agreement.superdocs import HttpSuperDocsClient
from payment_plan_agreement.workflow import AgreementWorkflow, Lifecycle


def main() -> int:
    if not os.environ.get("SUPERDOCS_API_KEY"):
        print("LIVE SUPERDOCS SMOKE TEST BLOCKED — SUPERDOCS_API_KEY MISSING")
        return 2
    request = CreatePlanRequest(
        creditor=Party(legal_name="Northstar Health Services"),
        debtor=Party(legal_name="Alex Morgan"),
        terms=PlanTerms(
            currency="USD", original_balance=Decimal("1000.00"), upfront_payment=Decimal("100.00"),
            installment_count=4, frequency=Frequency.MONTHLY, first_due_date=date(2026, 9, 15),
            agreement_date=date(2026, 8, 15), late_fee=LateFee(), reference_id="SYNTHETIC-LIVE-001",
        ),
    )
    started = time.monotonic()
    workflow = AgreementWorkflow(HttpSuperDocsClient())
    run = workflow.start(request)
    assert run.plan.terms.original_balance == Decimal("1000.00")
    assert run.plan.terms.upfront_payment == Decimal("100.00")
    assert run.plan.financed_balance == Decimal("900.00")
    assert len(run.plan.installments) == 4
    assert sum(item.amount for item in run.plan.installments) == Decimal("900.00")
    if run.state == Lifecycle.PROCESSING:
        workflow.wait_for_review(run)
    if run.state == Lifecycle.AWAITING_HUMAN:
        decisions = [ReviewDecision(change_id=item.change_id, approved=not item.blocked, feedback="Conflicts with canonical payment plan" if item.blocked else None) for item in run.job.proposals]
        workflow.review(run, decisions)
    if run.state != Lifecycle.FINAL_VERIFIED:
        raise RuntimeError(f"Final verification did not pass: {run.state.value}")
    exported = workflow.export(run)
    artifact_dir = Path("artifacts/live")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "payment-plan-demo.docx").write_bytes(exported.content)
    report = {
        "live": True, "test_data": "synthetic", "canonical_fingerprint": run.plan.semantic_fingerprint,
        "job_completed": bool(run.job and run.job.status == "completed"),
        "proposal_count": len(run.job.proposals) if run.job else 0,
        "approved_count": sum(item.approved for item in run.decisions),
        "rejected_count": sum(not item.approved for item in run.decisions),
        "final_verification": "pass", "export_format": "docx", "export_bytes": len(exported.content),
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/live-superdocs-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
