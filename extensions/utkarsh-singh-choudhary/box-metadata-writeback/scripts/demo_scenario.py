"""One coherent narrative, not scattered fixtures: Meridian Cold Chain
Logistics, a mid-size regulated freight brokerage, running Box as its
system of record for vendor contracts. This is the actual spine for the
Task 4 demo video and one-pager -- walks every file in demo_scenario/
through the real pipeline, shows the review queue, approves a held-back
field, checks the audit trail, and asks the governance simulator what
Box's own automation would now do with the result.

Run with: make demo-scenario
"""
from __future__ import annotations

import pathlib
from datetime import date

from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.models import GovernanceState
from app.workflow.governance_simulator import compute_governance_outcome
from app.workflow.history_store import MetadataHistoryStore
from app.workflow.pipeline import BoxMetadataWritebackPipeline
from app.workflow.review_queue import ReviewQueue

SCENARIO_DIR = pathlib.Path(__file__).resolve().parent.parent / "demo_scenario"


def load(name: str) -> bytes:
    return (SCENARIO_DIR / name).read_bytes()


def hr(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main() -> None:
    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    rq = ReviewQueue()
    hist = MetadataHistoryStore()
    pipeline = BoxMetadataWritebackPipeline(box, sd, review_queue=rq, history=hist)

    box.seed_file("msa-northbridge", "01_msa_northbridge.pdf", load("01_msa_northbridge.txt"))
    box.seed_file(
        "amendment-1-northbridge", "02_amendment_1_northbridge.pdf",
        load("02_amendment_1_northbridge.txt"),
    )
    box.seed_file("invoice-northbridge", "03_invoice_northbridge.pdf", load("03_invoice_northbridge.txt"))
    box.seed_file("policy-cold-chain", "04_cold_chain_policy.pdf", load("04_cold_chain_policy.txt"))
    box.seed_file(
        "msa-solara-hold", "05_msa_solara_under_legal_hold.pdf",
        load("05_msa_solara_under_legal_hold.txt"),
        governance=GovernanceState(legal_hold=True),
    )

    hr("Meridian Cold Chain Logistics -- 5 files land in Box")
    for file_id in (
        "msa-northbridge",
        "amendment-1-northbridge",
        "invoice-northbridge",
        "policy-cold-chain",
        "msa-solara-hold",
    ):
        report = pipeline.process(file_id)
        print(f"\n--- {file_id} ---")
        if report.skipped_reason:
            print(f"  SKIPPED: {report.skipped_reason}")
            continue
        for key, value in report.metadata_written.items():
            print(f"  {key}: {value}")
        if report.queued_for_review:
            print(f"  -> {len(report.queued_for_review)} field(s) held for human review")

    hr("Review queue: what's waiting on a human right now")
    pending = rq.list_pending()
    for review in pending:
        print(f"  [{review.review_id}] {review.file_id}.{review.field_name} = "
              f"{review.proposed_value!r} (confidence {review.confidence})")

    if pending:
        target = pending[0]
        hr(f"Approving {target.review_id} ({target.file_id}.{target.field_name})")
        result = pipeline.apply_review_decision(target.review_id, approve=True)
        print(f"  status: {result['status']}")
        md = box.get_metadata(target.file_id, "documentIntelligence")
        print(f"  {target.field_name} now in metadata: {md.get(target.field_name)!r}")

    hr("Audit trail for the northbridge MSA")
    for entry in hist.get_history("msa-northbridge"):
        print(f"  [{entry.reason}] {entry.field_name}: {entry.old_value!r} -> {entry.new_value!r}")

    hr("Governance outcome: does the metadata actually DO anything?")
    scenarios = [
        ("msa-northbridge", date(2027, 3, 1)),   # 7 years after its 2020-03-01 expiration
        ("policy-cold-chain", date(2027, 3, 1)),  # policy-indefinite: never auto-eligible
        ("msa-solara-hold", date(2027, 3, 1)),    # under legal hold: never eligible regardless
    ]
    for file_id, as_of in scenarios:
        metadata = box.get_metadata(file_id, "documentIntelligence")
        governance = box.get_governance_state(file_id)
        pending_fields = [r.field_name for r in rq.list_pending(file_id)]
        outcome = compute_governance_outcome(
            file_id, metadata, governance.legal_hold, governance.retention_policy_locked,
            pending_fields, today=as_of,
        )
        print(f"\n  {file_id} as of {as_of.isoformat()}:")
        print(f"    disposition_eligible_now = {outcome.disposition_eligible_now}")
        for r in outcome.retention_reasoning:
            print(f"      - {r}")
        print(f"    search_facets = {outcome.search_facets}")
        print(f"    workflows_triggered = {outcome.workflows_triggered}")
        print(f"    workflows_blocked = {outcome.workflows_blocked}")

    hr("Done -- this is the walkthrough Task 4's demo video follows")


if __name__ == "__main__":
    main()
