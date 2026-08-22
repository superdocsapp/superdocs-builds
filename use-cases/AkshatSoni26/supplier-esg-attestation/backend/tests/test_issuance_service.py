import pytest
from app.schemas.questionnaire import QuestionnaireIssuanceRequest
from app.services.issuance_service import IssuanceService


@pytest.mark.asyncio
async def test_issuance_tier1_eu(db_session):
    """Verify issuance correctly attaches Tier 1 Questionnaire and EU CSRD Addendum."""
    service = IssuanceService(db=db_session)
    response = await service.issue_questionnaire(QuestionnaireIssuanceRequest(
        supplier_id="sup-001-acme",
        cycle_year=2026
    ))

    assert response.supplier_name == "Acme Precision Components GmbH"
    assert response.tier == "TIER_1_STRATEGIC"
    assert response.region == "EU"
    assert "ANNEX T1: TIER 1 STRATEGIC ESG AUDIT QUESTIONNAIRE" in response.document_content_markdown
    assert "ANNEX R-EU: EUROPEAN UNION STATUTORY & CSRD COMPLIANCE ADDENDUM" in response.document_content_markdown
    assert response.superdocs_document_id is not None
    assert response.export_url is not None


@pytest.mark.asyncio
async def test_issuance_tier2_apac(db_session):
    """Verify issuance correctly attaches Tier 2 Questionnaire and APAC Labor Addendum."""
    service = IssuanceService(db=db_session)
    response = await service.issue_questionnaire(QuestionnaireIssuanceRequest(
        supplier_id="sup-002-apex",
        cycle_year=2026
    ))

    assert response.supplier_name == "Apex Electronics Manufacturing Ltd."
    assert response.tier == "TIER_2_MANUFACTURING"
    assert response.region == "APAC"
    assert "ANNEX T2: TIER 2 MANUFACTURING & PROCESSING ESG QUESTIONNAIRE" in response.document_content_markdown
    assert "ANNEX R-APAC: ASIA-PACIFIC REGIONAL LABOR & DISCHARGE ADDENDUM" in response.document_content_markdown
