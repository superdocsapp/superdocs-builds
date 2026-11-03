"""Runs the pipeline directly (no HTTP) against a few seeded scenarios and
prints the results -- the fastest way to see the whole thing work without
starting a server."""
from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.models import GovernanceState
from app.workflow.pipeline import BoxMetadataWritebackPipeline

CONTRACT = b"""SERVICES AGREEMENT
Counterparty: Acme Logistics Inc
Effective Date: 2026-01-15
Expiration Date: 2027-01-14
Value: $84,000
"""

INVOICE = b"""INVOICE\nAmount Due: $12,400\n"""


def main() -> None:
    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    pipeline = BoxMetadataWritebackPipeline(box, sd)

    box.seed_file("f-contract", "acme-msa.pdf", CONTRACT)
    box.seed_file("f-invoice", "acme-invoice.pdf", INVOICE)
    box.seed_file(
        "f-hold", "sealed.pdf", CONTRACT, governance=GovernanceState(legal_hold=True)
    )

    for file_id in ("f-contract", "f-invoice", "f-hold"):
        report = pipeline.process(file_id)
        print(f"\n=== {file_id} ===")
        if report.skipped_reason:
            print(f"skipped: {report.skipped_reason}")
        else:
            for k, v in report.metadata_written.items():
                print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
