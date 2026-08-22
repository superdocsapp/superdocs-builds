import json

from src.crm import FakeCRM
from src.proposal_engine import generate_proposal, verify_no_unfilled_placeholders, PROPOSAL_TEMPLATE, build_population_instruction
from src.fake_client import FakeSuperDocsClient


def _well_behaved_transform(deal):
    """Simulates a well-behaved AI that correctly substitutes every placeholder with the real deal value."""
    def _transform(html):
        replacements = {
            "[CLIENT COMPANY]": deal.client_company,
            "[CLIENT CONTACT NAME]": deal.client_contact_name,
            "[CLIENT CONTACT EMAIL]": deal.client_contact_email,
            "[PRODUCT NAME]": deal.product_name,
            "[DEAL VALUE]": f"${deal.deal_value_usd:,.2f}",
            "[CONTRACT LENGTH]": str(deal.contract_length_months),
            "[PAYMENT TERMS]": deal.payment_terms,
            "[SALES REP NAME]": deal.sales_rep_name,
            "[SALES REP EMAIL]": deal.sales_rep_email,
            "[DATE]": "August 22, 2026",
        }
        for k, v in replacements.items():
            html = html.replace(k, v)
        return html
    return _transform


def test_proposal_is_populated_with_real_deal_fields():
    crm = FakeCRM()
    deal = crm.get_deal("deal-001")
    client = FakeSuperDocsClient()
    client.script_edit("Replace EVERY placeholder", _well_behaved_transform(deal))

    draft = generate_proposal(client, deal, session_id="proposal-deal-001")

    assert deal.client_company in draft.html
    assert deal.client_contact_email in draft.html
    assert "$84,000.00" in draft.html
    assert "12" in draft.html  # contract length


def test_no_unfilled_placeholders_after_correct_population():
    crm = FakeCRM()
    deal = crm.get_deal("deal-001")
    client = FakeSuperDocsClient()
    client.script_edit("Replace EVERY placeholder", _well_behaved_transform(deal))

    draft = generate_proposal(client, deal, session_id="proposal-deal-001")
    assert verify_no_unfilled_placeholders(draft.html) == []


def test_unfilled_placeholder_is_detected_not_silently_shipped():
    """If the AI fails to fill a field (simulated here by a transform that skips one), the sanity check
    must catch it -- a proposal with a literal '[PAYMENT TERMS]' visible to a real client is a real
    embarrassment this check exists to prevent."""
    crm = FakeCRM()
    deal = crm.get_deal("deal-001")
    client = FakeSuperDocsClient()

    def incomplete_transform(html):
        # deliberately forgets to replace [PAYMENT TERMS]
        return html.replace("[CLIENT COMPANY]", deal.client_company)

    client.script_edit("Replace EVERY placeholder", incomplete_transform)
    draft = generate_proposal(client, deal, session_id="proposal-deal-001")

    unfilled = verify_no_unfilled_placeholders(draft.html)
    assert "[PAYMENT TERMS]" in unfilled


def test_instruction_grounds_every_value_in_the_real_deal_no_invented_fields():
    crm = FakeCRM()
    deal = crm.get_deal("deal-002")
    instruction = build_population_instruction(deal)
    assert deal.client_company in instruction
    assert "19,500.00" in instruction
    assert "do not invent" in instruction.lower()
