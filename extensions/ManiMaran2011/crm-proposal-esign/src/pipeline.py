"""
Orchestrates the full pipeline. The human gate is structural: `run_pipeline` STOPS after generating the
draft and returns it for review; `send_approved_proposal` is a SEPARATE function that must be called
explicitly, with an explicit `approved=True`, to proceed to the e-sign step. There is no code path that
goes from CRM record to sent envelope without an explicit second call in between -- mirrors Task 1's
graph-level interrupt, just expressed as two separate functions instead of a graph node, since this
pipeline is linear rather than branching.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.crm import Deal, FakeCRM
from src.proposal_engine import generate_proposal, verify_no_unfilled_placeholders, ProposalDraft
from src.esign_client import EsignProvider, EnvelopeResult


@dataclass
class PipelineResult:
    draft: ProposalDraft
    unfilled_placeholders: list[str]
    ready_for_approval: bool


def run_pipeline(client, crm: FakeCRM, deal_id: str) -> PipelineResult:
    """Stage 1: CRM -> populated proposal draft. Does NOT send anything anywhere. Returns the draft plus an
    honest readiness check -- if any placeholder failed to populate, `ready_for_approval` is False and the
    human reviewing this should see exactly which fields are missing before being asked to approve."""
    deal = crm.get_deal(deal_id)
    if deal is None:
        raise ValueError(f"No such deal: {deal_id}")

    session_id = f"proposal-{deal_id}"
    draft = generate_proposal(client, deal, session_id)
    unfilled = verify_no_unfilled_placeholders(draft.html)

    return PipelineResult(draft=draft, unfilled_placeholders=unfilled, ready_for_approval=not unfilled)


def send_approved_proposal(
    superdocs_client, esign_provider: EsignProvider, draft: ProposalDraft, deal: Deal, approved: bool,
) -> EnvelopeResult | None:
    """Stage 2: only reachable with an EXPLICIT approved=True from whoever is driving this (human or a
    machine acting on the human's explicit instruction, per Task 1's same principle). Exports the approved
    document from SuperDocs, then hands the PDF bytes to the e-sign provider -- SuperDocs' involvement ends
    at the export() call; everything after that line is the e-sign provider's job."""
    if not approved:
        return None  # explicit no-op, not an exception -- rejecting a proposal is a normal, valid outcome

    pdf_bytes = superdocs_client.export(draft.session_id, fmt="pdf")

    return esign_provider.send_for_signature(
        pdf_bytes=pdf_bytes,
        signer_name=deal.client_contact_name,
        signer_email=deal.client_contact_email,
        subject=f"Proposal for {deal.client_company} — please sign",
    )
