import pytest
from app.schemas.followup import FollowUpLetterCreate
from app.services.follow_up_service import FollowUpService


@pytest.mark.asyncio
async def test_follow_up_letter_generation_with_quotes(db_session):
    """Verify follow-up letter drafts properly and quotes the supplier's actual statement."""
    service = FollowUpService(db=db_session)
    letter = await service.generate_follow_up_letter(FollowUpLetterCreate(
        attestation_id="att-acme-2026",
        custom_remediation_deadline_days=30
    ))

    assert letter.recipient_email == "compliance@acme-precision.de"
    assert "ESG Attestation Remediation Notice" in letter.subject
    assert "FORMAL ESG AUDIT REMEDIATION NOTICE" in letter.content_markdown
    # Verify exact quote is present in the markdown letter
    assert "We currently do not track Scope 2 indirect emissions from electricity consumption." in letter.content_markdown
    assert letter.superdocs_doc_id is not None
