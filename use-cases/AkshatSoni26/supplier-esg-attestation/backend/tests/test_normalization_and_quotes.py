import pytest
from app.services.normalization_service import NormalizationService
from app.schemas.enums import FindingSeverity, RiskTier


def test_normalization_and_exact_verbatim_quote():
    """Verify normalization extracts gaps and quotes the supplier's verbatim response."""
    service = NormalizationService(db=None)

    raw_response = """
    COMPANY ATTESTATION RETURN - APEX ELECTRONICS
    
    1. Environmental Disclosures:
    Scope 1 Emissions: 1,420 MT CO2e calculated per GHG protocol.
    Scope 2 Emissions: 3,100 MT CO2e.
    Renewable Energy: 25% clean solar mix.
    ISO 14001: Certified until 2028.
    
    2. Labor and Social Disclosures:
    During peak production seasons, workers operate up to 72 hours per week to meet quota deadlines.
    Recruitment agency fees are deducted across the first 6 months of employment.
    
    3. Governance:
    Anti-bribery policy: Formal anti-corruption training is currently informal and not documented.
    Whistleblower channel: Active anonymous email inbox.
    """

    result = service.analyze_response_text(
        raw_text=raw_response,
        tier="TIER_2_MANUFACTURING",
        region="APAC",
        supplier_name="Apex Electronics Manufacturing Ltd."
    )

    assert result.overall_risk_score > 50.0
    assert result.risk_tier in [RiskTier.CRITICAL, RiskTier.HIGH]
    assert len(result.findings) >= 2

    # Check that excessive working hours finding contains the exact quote
    working_hours_finding = next(
        f for f in result.findings if "Working Hours" in f.standard_clause or "72" in f.shortfall_summary
    )
    assert working_hours_finding.severity == FindingSeverity.CRITICAL
    assert "During peak production seasons, workers operate up to 72 hours per week to meet quota deadlines." in working_hours_finding.supplier_exact_quote

    # Check that recruitment fee finding contains the exact quote
    recruitment_finding = next(
        f for f in result.findings if "Recruitment Fee" in f.standard_clause
    )
    assert recruitment_finding.severity == FindingSeverity.CRITICAL
    assert "Recruitment agency fees are deducted across the first 6 months of employment." in recruitment_finding.supplier_exact_quote


def test_clean_supplier_honest_zero_findings():
    """Verify that a compliant supplier produces an honest report of 0 findings."""
    service = NormalizationService(db=None)

    clean_response = """
    COMPANY ATTESTATION RETURN - NORDIC CLEANTECH
    
    1. Environmental Disclosures:
    Scope 1 Emissions: 210 MT CO2e.
    Scope 2 Emissions: 45 MT CO2e certified by third-party audit.
    Scope 3: Tracked across Category 1 purchased goods.
    Renewable Energy: 100% certified wind and hydro power.
    ISO 14001: Certified EMS with annual surveillance audits.
    
    2. Labor and Social Disclosures:
    Forced labor prohibition: Strict zero tolerance policy.
    Child labor prohibition: Strict zero tolerance policy.
    Standard weekly working hours are 40 hours per week, with max 8 hours voluntary overtime.
    Living wage guarantee: 100% workers earn above collective bargaining living wage.
    Worker grievance mechanism: Independent anonymous ombudsman hotline.
    
    3. Governance:
    Anti-bribery policy: Formal code of ethics with mandatory annual certified testing.
    Whistleblower protection: Encrypted anonymous reporting portal.
    Chain of custody: 100% sub-tier supplier provenance tracked.
    """

    result = service.analyze_response_text(
        raw_text=clean_response,
        tier="TIER_1_STRATEGIC",
        region="EU",
        supplier_name="Nordic CleanTech Solutions AB"
    )

    assert result.risk_tier == RiskTier.LOW
    assert result.overall_risk_score < 20.0
    assert len(result.findings) == 0
    assert "0 compliance shortfalls" in result.executive_summary
