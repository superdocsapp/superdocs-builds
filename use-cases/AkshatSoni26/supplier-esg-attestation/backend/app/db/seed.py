import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import SupplierModel, AttestationCycleModel, AssessmentModel, FindingModel
from app.schemas.enums import SupplierTier, Region, AttestationStatus, ESGPillar, FindingSeverity, ReviewDecision, RiskTier


INITIAL_SUPPLIERS = [
    {
        "id": "sup-001-acme",
        "name": "Acme Precision Components GmbH",
        "code": "SUP-ACME-01",
        "tier": SupplierTier.TIER_1_STRATEGIC.value,
        "region": Region.EU.value,
        "country": "Germany",
        "primary_contact_email": "compliance@acme-precision.de"
    },
    {
        "id": "sup-002-apex",
        "name": "Apex Electronics Manufacturing Ltd.",
        "code": "SUP-APEX-02",
        "tier": SupplierTier.TIER_2_MANUFACTURING.value,
        "region": Region.APAC.value,
        "country": "Taiwan",
        "primary_contact_email": "esg-office@apex-semi.tw"
    },
    {
        "id": "sup-003-zenith",
        "name": "Zenith Global Minerals & Logistics Corp.",
        "code": "SUP-ZENITH-03",
        "tier": SupplierTier.TIER_3_COMMODITY.value,
        "region": Region.NORTH_AMERICA.value,
        "country": "United States",
        "primary_contact_email": "sustainability@zenithminerals.com"
    },
    {
        "id": "sup-004-nordic",
        "name": "Nordic CleanTech Solutions AB",
        "code": "SUP-NORDIC-04",
        "tier": SupplierTier.TIER_1_STRATEGIC.value,
        "region": Region.EU.value,
        "country": "Sweden",
        "primary_contact_email": "audit@nordiccleantech.se"
    },
    {
        "id": "sup-005-pacific",
        "name": "Pacific Industrial Assemblies Co.",
        "code": "SUP-PACIFIC-05",
        "tier": SupplierTier.TIER_2_MANUFACTURING.value,
        "region": Region.APAC.value,
        "country": "Vietnam",
        "primary_contact_email": "esg@pacificassemblies.vn"
    }
]


async def seed_initial_data(db: AsyncSession):
    """Seed base suppliers and sample attestation cycles if empty."""
    # Check if suppliers exist
    res = await db.execute(select(SupplierModel))
    if res.scalars().first():
        return  # Already seeded

    for sup_data in INITIAL_SUPPLIERS:
        supplier = SupplierModel(**sup_data)
        db.add(supplier)

    await db.commit()

    # Pre-seed one completed attestation with findings for immediate visual demo
    acme_att = AttestationCycleModel(
        id="att-acme-2026",
        supplier_id="sup-001-acme",
        cycle_year=2026,
        status=AttestationStatus.FOLLOW_UP_REQUIRED.value,
        issued_document_id="sd-doc-acme-issued",
        issued_document_url="/api/v1/superdocs/download/acme_questionnaire.pdf",
        response_document_id="sd-doc-acme-resp",
        response_document_name="acme_esg_response_2026.pdf",
        response_format="PDF",
        submitted_at=datetime.now(timezone.utc),
        normalized_at=datetime.now(timezone.utc)
    )
    db.add(acme_att)
    await db.flush()

    acme_ass = AssessmentModel(
        id="ass-acme-2026",
        attestation_id=acme_att.id,
        overall_risk_score=52.5,
        risk_tier=RiskTier.HIGH.value,
        environmental_score=50.0,
        social_score=85.0,
        governance_score=60.0,
        summary_markdown="Acme Precision completed the Tier 1 attestation. Scope 2 emissions verification missing.",
        is_approved=False
    )
    db.add(acme_ass)
    await db.flush()

    acme_finding = FindingModel(
        id="find-acme-01",
        assessment_id=acme_ass.id,
        pillar=ESGPillar.ENVIRONMENTAL.value,
        severity=FindingSeverity.HIGH.value,
        standard_clause="Clause E1.1: Mandatory Annual Scope 1 & 2 GHG Disclosures",
        shortfall_summary="Supplier failed to calculate or verify Scope 2 greenhouse gas emissions.",
        supplier_exact_quote="We currently do not track Scope 2 indirect emissions from electricity consumption.",
        source_location="Section 2.1 Emissions Log",
        recommended_action="Execute Scope 2 inventory based on utility electricity bills and submit third-party audit within 30 days.",
        review_decision=ReviewDecision.PENDING.value
    )
    db.add(acme_finding)

    # Pre-seed Nordic as a clean baseline (honest zero findings)
    nordic_att = AttestationCycleModel(
        id="att-nordic-2026",
        supplier_id="sup-004-nordic",
        cycle_year=2026,
        status=AttestationStatus.APPROVED.value,
        issued_document_id="sd-doc-nordic-issued",
        issued_document_url="/api/v1/superdocs/download/nordic_questionnaire.pdf",
        response_document_id="sd-doc-nordic-resp",
        response_document_name="nordic_sustainability_report.pdf",
        response_format="PDF",
        submitted_at=datetime.now(timezone.utc),
        normalized_at=datetime.now(timezone.utc)
    )
    db.add(nordic_att)
    await db.flush()

    nordic_ass = AssessmentModel(
        id="ass-nordic-2026",
        attestation_id=nordic_att.id,
        overall_risk_score=12.0,
        risk_tier=RiskTier.LOW.value,
        environmental_score=98.0,
        social_score=95.0,
        governance_score=100.0,
        summary_markdown="Nordic CleanTech completed Tier 1 attestation with exemplary scores. 0 findings identified.",
        is_approved=True,
        approved_by="Compliance Director",
        approved_at=datetime.now(timezone.utc)
    )
    db.add(nordic_ass)

    await db.commit()
