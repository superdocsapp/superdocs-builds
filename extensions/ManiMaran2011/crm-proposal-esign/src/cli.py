"""
Usage:
    python -m src.cli run deal-001
"""
from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

from src.client import SuperDocsClient
from src.crm import FakeCRM
from src.esign_client import DocuSignMCPClient
from src.pipeline import run_pipeline, send_approved_proposal


def run(deal_id: str):
    crm = FakeCRM()
    deal = crm.get_deal(deal_id)
    if deal is None:
        print(f"No such deal: {deal_id}. Available: {[d.deal_id for d in crm.list_deals()]}")
        sys.exit(1)

    print(f"Deal: {deal.client_company} — ${deal.deal_value_usd:,.2f} — {deal.product_name}")

    client = SuperDocsClient()
    result = run_pipeline(client, crm, deal_id)

    if not result.ready_for_approval:
        print(f"NOT ready for approval — unfilled placeholders: {result.unfilled_placeholders}")
        print("Fix the population instruction or template before proceeding.")
        return

    print("\n--- DRAFT PROPOSAL (review before approving) ---")
    print(result.draft.html[:2000])
    print("--- end of draft preview ---\n")

    answer = input(f"Approve and send to {deal.client_contact_name} <{deal.client_contact_email}> for signature? [y/N] ")
    approved = answer.strip().lower() == "y"

    if not approved:
        print("Rejected. Nothing sent.")
        return

    print("Approved. Handing off to DocuSign for signature routing...")
    esign = DocuSignMCPClient()  # reads DOCUSIGN_ACCESS_TOKEN / DOCUSIGN_ACCOUNT_ID from env
    outcome = send_approved_proposal(client, esign, result.draft, deal, approved=True)

    print(f"Envelope sent via {outcome.provider}. Envelope ID: {outcome.envelope_id}. Status: {outcome.status}")
    print("SuperDocs' involvement ends here -- DocuSign now owns delivery, reminders, and signature tracking.")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "run":
        print("Usage: python -m src.cli run <deal-id>   (try: deal-001 or deal-002)")
        sys.exit(1)
    run(sys.argv[2])
