"""
Builds a proposal document from a CRM deal, using a SuperDocs proposal template as the starting point and a
single scoped chat instruction to populate it -- not a from-scratch generation, and not a naive string
find-replace, since the task card explicitly wants "a SuperDocs proposal template with real branding and
terms."
"""
from __future__ import annotations

from dataclasses import dataclass

from src.crm import Deal


@dataclass
class ProposalDraft:
    session_id: str
    html: str
    deal_id: str


PROPOSAL_TEMPLATE = """
<h1>Sales Proposal</h1>
<p><em>Prepared for: [CLIENT COMPANY] — [DATE]</em></p>

<h2>Prepared For</h2>
<p>[CLIENT CONTACT NAME]<br/>[CLIENT COMPANY]<br/>[CLIENT CONTACT EMAIL]</p>

<h2>Proposed Solution</h2>
<p>[PRODUCT NAME]</p>

<h2>Commercial Terms</h2>
<ul>
<li>Total contract value: [DEAL VALUE]</li>
<li>Contract length: [CONTRACT LENGTH] months</li>
<li>Payment terms: [PAYMENT TERMS]</li>
</ul>

<h2>Prepared By</h2>
<p>[SALES REP NAME]<br/>[SALES REP EMAIL]</p>

<h2>Signatures</h2>
<p>By signing below, both parties agree to the terms outlined in this proposal.</p>
<p>_________________________ &nbsp;&nbsp;&nbsp; Date: __________</p>
<p>[CLIENT CONTACT NAME], [CLIENT COMPANY]</p>
"""


def build_population_instruction(deal: Deal) -> str:
    """A single scoped instruction listing every field to populate, each with an explicit source value --
    this is what stops the model from inventing plausible-looking placeholder data for a field it doesn't
    have real information for; every value here is grounded in the actual CRM record, not guessed."""
    return (
        "This document is a proposal TEMPLATE with bracketed placeholders. Replace EVERY placeholder with "
        "the exact value given below -- do not invent, estimate, or embellish any value not listed here. "
        "If a placeholder has no corresponding value below, leave it as-is and do not guess.\n\n"
        f"[CLIENT COMPANY] -> {deal.client_company}\n"
        f"[CLIENT CONTACT NAME] -> {deal.client_contact_name}\n"
        f"[CLIENT CONTACT EMAIL] -> {deal.client_contact_email}\n"
        f"[PRODUCT NAME] -> {deal.product_name}\n"
        f"[DEAL VALUE] -> ${deal.deal_value_usd:,.2f}\n"
        f"[CONTRACT LENGTH] -> {deal.contract_length_months}\n"
        f"[PAYMENT TERMS] -> {deal.payment_terms}\n"
        f"[SALES REP NAME] -> {deal.sales_rep_name}\n"
        f"[SALES REP EMAIL] -> {deal.sales_rep_email}\n"
        f"[DATE] -> (use today's date)\n\n"
        "Do not add any sections, commentary, or content beyond filling in these placeholders."
    )


def generate_proposal(client, deal: Deal, session_id: str) -> ProposalDraft:
    instruction = build_population_instruction(deal)
    response = client.chat(session_id=session_id, message=instruction, document_html=PROPOSAL_TEMPLATE)
    html = response["document_changes"]["updated_html"]
    return ProposalDraft(session_id=session_id, html=html, deal_id=deal.deal_id)


def verify_no_unfilled_placeholders(html: str) -> list[str]:
    """A cheap, deterministic sanity check run BEFORE showing the draft to a human for approval: any
    bracketed placeholder still present means the population step failed for that field, and this should
    be surfaced rather than silently approved-and-sent with a literal '[CLIENT COMPANY]' still in the
    document a real client would see."""
    import re
    return re.findall(r"\[[A-Z][A-Z \n]*\]", html)
