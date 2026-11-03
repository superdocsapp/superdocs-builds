"""The task card is explicit: "works the second time, on a second run
with different documents, not just in the demo." This is that second
run: a different counterparty (Solstice Freight Underwriters, not
Northbridge/Meridian), a different document mix (an invoice with a
different label format, an informal email thread with no labeled
fields at all, a policy doc that reuses and extends the negation
phrasing an earlier bug mishandled, and a second legal-hold file with a
different narrative reason for the hold), run through the exact same
pipeline code as demo_scenario.py with zero changes.

Run with: make demo-scenario-2
"""
from __future__ import annotations

import pathlib

from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.models import GovernanceState
from app.workflow.pipeline import BoxMetadataWritebackPipeline

SCENARIO_DIR = pathlib.Path(__file__).resolve().parent.parent / "demo_scenario_2"


def load(name: str) -> bytes:
    return (SCENARIO_DIR / name).read_bytes()


def hr(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main() -> None:
    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    pipeline = BoxMetadataWritebackPipeline(box, sd)

    box.seed_file("msa-solstice", "01_msa_solstice.pdf", load("01_msa_solstice.txt"))
    box.seed_file("invoice-solstice", "02_invoice_solstice.pdf", load("02_invoice_solstice.txt"))
    box.seed_file("email-solstice", "03_email_thread_solstice.pdf", load("03_email_thread_solstice.txt"))
    box.seed_file("policy-underwriting", "04_underwriting_policy.pdf", load("04_underwriting_policy.txt"))
    box.seed_file(
        "msa-solstice-hold", "05_msa_solstice_under_hold.pdf",
        load("05_msa_solstice_under_hold.txt"),
        governance=GovernanceState(legal_hold=True),
    )

    hr("Solstice Freight Underwriters -- a different vendor, second run, zero code changes")
    for file_id in (
        "msa-solstice",
        "invoice-solstice",
        "email-solstice",
        "policy-underwriting",
        "msa-solstice-hold",
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

    hr("Done -- same pipeline, same code, genuinely different documents")


if __name__ == "__main__":
    main()
