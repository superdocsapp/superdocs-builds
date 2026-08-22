"""
Database Reset & Re-seeding Script for SuperDocs Task 2.
Resets SQLite database and seeds a comprehensive set of suppliers across ALL lifecycle stages:
1. Acme Precision (T1 EU) -> FOLLOW_UP_REQUIRED (High Risk, 1 Finding: Scope 2)
2. Apex Electronics (T2 APAC) -> FOLLOW_UP_REQUIRED (Critical Risk, 3 Findings: 72h Overtime, Recruitment Fees)
3. Nordic CleanTech (T1 EU) -> APPROVED (Low Risk, 0 Gaps Clean Baseline)
4. Pacific Industrial (T2 APAC) -> ISSUED (Ready for upload)
5. Zenith Minerals (T3 NA) -> NOT ISSUED (Ready for issuance)
"""
import asyncio
import os
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine
from app.db.base import Base
from app.db.session import AsyncSessionLocal
from app.db.models import SupplierModel, AttestationCycleModel, AssessmentModel, FindingModel
from app.schemas.enums import SupplierTier, Region, AttestationStatus, ESGPillar, FindingSeverity, ReviewDecision, RiskTier
from app.core.config import settings

INITIAL_SUPPLIERS = [
    {
        "id": "sup-001-acme",
        "name": "Acme Precision Components GmbH",
        "code": "SUP-ACME-01",
        "tier": SupplierTier.TIER_1_STRATEGIC.value,
        "region": Region.EU.value,
        "country": "Germany",
        "primary_contact_email": "compliance@acme-precision.de",
    },
    {
        "id": "sup-002-apex",
        "name": "Apex Electronics Manufacturing Ltd.",
        "code": "SUP-APEX-02",
        "tier": SupplierTier.TIER_2_MANUFACTURING.value,
        "region": Region.APAC.value,
        "country": "Taiwan",
        "primary_contact_email": "esg-office@apex-semi.tw",
    },
    {
        "id": "sup-003-zenith",
        "name": "Zenith Global Minerals & Logistics Corp.",
        "code": "SUP-ZENITH-03",
        "tier": SupplierTier.TIER_3_COMMODITY.value,
        "region": Region.NORTH_AMERICA.value,
        "country": "United States",
        "primary_contact_email": "sustainability@zenithminerals.com",
    },
    {
        "id": "sup-004-nordic",
        "name": "Nordic CleanTech Solutions AB",
        "code": "SUP-NORDIC-04",
        "tier": SupplierTier.TIER_1_STRATEGIC.value,
        "region": Region.EU.value,
        "country": "Sweden",
        "primary_contact_email": "audit@nordiccleantech.se",
    },
    {
        "id": "sup-005-pacific",
        "name": "Pacific Industrial Assemblies Co.",
        "code": "SUP-PACIFIC-05",
        "tier": SupplierTier.TIER_2_MANUFACTURING.value,
        "region": Region.APAC.value,
        "country": "Vietnam",
        "primary_contact_email": "esg@pacificassemblies.vn",
    },
]


async def reset_database():
    db_file = "task2_esg.db"
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
            print(f"✓ Removed existing database: {db_file}")
        except Exception as e:
            print(f"! Notice on removing db_file: {e}")

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        print("✓ Created database schema tables.")

    async with AsyncSessionLocal() as session:
        # 1. Add Suppliers
        for s_data in INITIAL_SUPPLIERS:
            supplier = SupplierModel(**s_data)
            session.add(supplier)
        await session.flush()

        # 2. Case 1: Acme Precision (T1 EU) -> FOLLOW_UP_REQUIRED (High Risk)
        acme_att = AttestationCycleModel(
            id="att-acme-2026",
            supplier_id="sup-001-acme",
            cycle_year=2026,
            status=AttestationStatus.FOLLOW_UP_REQUIRED.value,
            issued_document_id="sd-doc-acme-issued",
            issued_document_url="/api/v1/superdocs/download/acme_questionnaire.pdf",
            response_document_id="sd-doc-acme-resp",
            response_document_name="acme_industrial_tier1_eu.txt",
            response_format="TXT",
            submitted_at=datetime.now(timezone.utc),
            normalized_at=datetime.now(timezone.utc),
        )
        session.add(acme_att)
        await session.flush()

        acme_ass = AssessmentModel(
            id="ass-acme-2026",
            attestation_id=acme_att.id,
            overall_risk_score=52.5,
            risk_tier=RiskTier.HIGH.value,
            environmental_score=50.0,
            social_score=85.0,
            governance_score=60.0,
            summary_markdown="Acme Precision completed Tier 1 attestation. Scope 2 emissions verification missing.",
            is_approved=False,
        )
        session.add(acme_ass)
        await session.flush()

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
            review_decision=ReviewDecision.PENDING.value,
        )
        session.add(acme_finding)

        # 3. Case 2: Apex Electronics (T2 APAC) -> FOLLOW_UP_REQUIRED (Critical Risk)
        apex_att = AttestationCycleModel(
            id="att-apex-2026",
            supplier_id="sup-002-apex",
            cycle_year=2026,
            status=AttestationStatus.FOLLOW_UP_REQUIRED.value,
            issued_document_id="sd-doc-apex-issued",
            issued_document_url="/api/v1/superdocs/download/apex_questionnaire.pdf",
            response_document_id="sd-doc-apex-resp",
            response_document_name="apex_electronics_tier2_apac.txt",
            response_format="TXT",
            submitted_at=datetime.now(timezone.utc),
            normalized_at=datetime.now(timezone.utc),
        )
        session.add(apex_att)
        await session.flush()

        apex_ass = AssessmentModel(
            id="ass-apex-2026",
            attestation_id=apex_att.id,
            overall_risk_score=84.1,
            risk_tier=RiskTier.CRITICAL.value,
            environmental_score=85.0,
            social_score=40.0,
            governance_score=60.0,
            summary_markdown="Apex Electronics flagged for critical ILO labor and overtime violations.",
            is_approved=False,
        )
        session.add(apex_ass)
        await session.flush()

        apex_findings = [
            FindingModel(
                id="find-apex-01",
                assessment_id=apex_ass.id,
                pillar=ESGPillar.SOCIAL.value,
                severity=FindingSeverity.CRITICAL.value,
                standard_clause="Clause S1.2: Maximum Working Hours & Overtime Caps (ILO C001)",
                shortfall_summary="Working hours exceed statutory 60h/week cap during peak production.",
                supplier_exact_quote="During peak production seasons, workers operate up to 72 hours per week.",
                source_location="Labor Log Pg 4",
                recommended_action="Immediately cap shifts at 60 hours/week and institute mandatory rest days.",
                review_decision=ReviewDecision.PENDING.value,
            ),
            FindingModel(
                id="find-apex-02",
                assessment_id=apex_ass.id,
                pillar=ESGPillar.SOCIAL.value,
                severity=FindingSeverity.HIGH.value,
                standard_clause="Clause S2.1: Employer-Pays Principle & Recruitment Fee Prohibition",
                shortfall_summary="Deductions made from migrant worker wages for agency recruitment fees.",
                supplier_exact_quote="Recruitment agency fees are deducted from migrant worker payroll over 6 months.",
                source_location="Payroll Appendix B",
                recommended_action="Reimburse all recruitment fees to workers and adopt Employer-Pays contract clauses.",
                review_decision=ReviewDecision.PENDING.value,
            ),
            FindingModel(
                id="find-apex-03",
                assessment_id=apex_ass.id,
                pillar=ESGPillar.GOVERNANCE.value,
                severity=FindingSeverity.MEDIUM.value,
                standard_clause="Clause G1.3: Anonymous Whistleblower Hotline",
                shortfall_summary="Grievances reported to direct supervisors without external anonymity channel.",
                supplier_exact_quote="All workplace grievances are resolved internally by floor supervisors.",
                source_location="HR Policy 3.2",
                recommended_action="Implement independent third-party confidential whistleblowing hotline.",
                review_decision=ReviewDecision.PENDING.value,
            ),
        ]
        for f in apex_findings:
            session.add(f)

        # 4. Case 3: Nordic CleanTech (T1 EU) -> APPROVED (Low Risk Clean Baseline)
        nordic_att = AttestationCycleModel(
            id="att-nordic-2026",
            supplier_id="sup-004-nordic",
            cycle_year=2026,
            status=AttestationStatus.APPROVED.value,
            issued_document_id="sd-doc-nordic-issued",
            issued_document_url="/api/v1/superdocs/download/nordic_questionnaire.pdf",
            response_document_id="sd-doc-nordic-resp",
            response_document_name="nordic_cleantech_clean_baseline.txt",
            response_format="TXT",
            submitted_at=datetime.now(timezone.utc),
            normalized_at=datetime.now(timezone.utc),
        )
        session.add(nordic_att)
        await session.flush()

        nordic_ass = AssessmentModel(
            id="ass-nordic-2026",
            attestation_id=nordic_att.id,
            overall_risk_score=5.2,
            risk_tier=RiskTier.LOW.value,
            environmental_score=85.0,
            social_score=100.0,
            governance_score=100.0,
            summary_markdown="Nordic CleanTech completed Tier 1 attestation with exemplary scores. 0 findings identified.",
            is_approved=True,
            approved_by="Compliance Director",
            approved_at=datetime.now(timezone.utc),
        )
        session.add(nordic_ass)

        # 5. Case 4: Pacific Industrial (T2 APAC) -> ISSUED (Ready for upload)
        pacific_att = AttestationCycleModel(
            id="att-pacific-2026",
            supplier_id="sup-005-pacific",
            cycle_year=2026,
            status=AttestationStatus.ISSUED.value,
            issued_document_id="sd-doc-pacific-issued",
            issued_document_url="/api/v1/superdocs/download/pacific_questionnaire.pdf",
        )
        session.add(pacific_att)

        # 6. Case 5: Zenith Minerals (T3 NA) -> DRAFT / NOT ISSUED (Ready for issuance)

        await session.commit()
        print("✓ Successfully seeded all 5 diverse lifecycle cases:")
        print("  - Acme Precision: FOLLOW_UP_REQUIRED (High Risk · 1 Finding)")
        print("  - Apex Electronics: FOLLOW_UP_REQUIRED (Critical Risk · 3 Findings)")
        print("  - Nordic CleanTech: APPROVED (Low Risk · 0 Findings Clean)")
        print("  - Pacific Industrial: ISSUED (Ready for 'Upload Response')")
        print("  - Zenith Minerals: NOT ISSUED (Ready for 'Issue Package')")

    print("\n🎉 Database reset complete! All cases and workflow buttons are live:")
    print("  • Tab 1: View all 4 workflow action buttons across suppliers.")
    print("  • Tab 2: View full Donut, Bar Chart & Pillar scores.")
    print("  • Tab 3: View all verbatim quotes & download executive PDF.")


if __name__ == "__main__":
    asyncio.run(reset_database())
