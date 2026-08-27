from orchestrator.orchestrator import Orchestrator


def test_fragment_instructions_sends_one_flattened_section_replacement() -> None:
    before = (
        "Contract Reference:\n"
        "MSA-2026-00417 (Masster Services Agreement, effective 03/03/2026)\n"
        "Ammendment Reference:\n"
        "AMD-01, executed 07/15/2026 — added On-site Emerjency Response line item; "
        "revvised Application Support & Maintenance annual estimated hours from 300 to 400\n"
        "Billing Period:\nJuly 1–31, 2026\nPurchase Order #: PO-MRH-88123"
    )
    after = (
        "Contract Reference:\n"
        "MSA-2026-00417 (Master Services Agreement, effective 03/03/2026)\n"
        "Amendment Reference:\n"
        "AMD-01, executed 07/15/2026 — added On-site Emergency Response line item; "
        "revised Application Support & Maintenance annual estimated hours from 300 to 400\n"
        "Billing Period:\nJuly 1–31, 2026\nPurchase Order #: PO-MRH-88123"
    )

    message = Orchestrator.fragment_instructions(
        "payment-terms", before, after)

    assert message == (
        "For section Payment Terms, find the text 'Contract Reference: MSA-2026-00417 "
        "(Masster Services Agreement, effective 03/03/2026) Ammendment Reference: "
        "AMD-01, executed 07/15/2026 — added On-site Emerjency Response line item; "
        "revvised Application Support & Maintenance annual estimated hours from 300 to 400 "
        "Billing Period: July 1–31, 2026 Purchase Order #: PO-MRH-88123' and update exactly "
        "with 'Contract Reference: MSA-2026-00417 (Master Services Agreement, effective "
        "03/03/2026) Amendment Reference: AMD-01, executed 07/15/2026 — added On-site "
        "Emergency Response line item; revised Application Support & Maintenance annual "
        "estimated hours from 300 to 400 Billing Period: July 1–31, 2026 Purchase Order #: "
        "PO-MRH-88123'."
    )
    assert "\n" not in message
