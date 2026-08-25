from collections import Counter
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import SupplierModel, AttestationCycleModel, AssessmentModel, FindingModel
from app.schemas.enums import SupplierTier, Region, RiskTier, AttestationStatus
from app.schemas.report import (
    ProgrammeReportResponse,
    RiskDistributionItem,
    PillarAverageScores,
    TierRiskData,
    RegionalRiskData,
    TopFindingShortfall,
)
from app.services.superdocs_service import SuperDocsClientService
from app.helpers.template_renderer import TemplateRenderer


class AggregationService:
    """Service to aggregate supplier attestation data and compile executive programme reports with charts."""

    def __init__(self, db: AsyncSession, superdocs_client: SuperDocsClientService | None = None):
        self.db = db
        self.superdocs = superdocs_client or SuperDocsClientService()

    async def get_programme_metrics(self, cycle_year: int = 2026) -> ProgrammeReportResponse:
        # 1. Fetch all suppliers
        sup_stmt = select(SupplierModel)
        sup_res = await self.db.execute(sup_stmt)
        suppliers = list(sup_res.scalars().all())
        total_invited = len(suppliers)

        tier_stats: dict[str, dict[str, int]] = {
            t.value: {
                "total": 0,
                RiskTier.LOW.value: 0,
                RiskTier.MEDIUM.value: 0,
                RiskTier.HIGH.value: 0,
                RiskTier.CRITICAL.value: 0,
            }
            for t in SupplierTier
        }
        reg_stats: dict[str, dict[str, int]] = {
            r.value: {
                "total": 0,
                RiskTier.LOW.value: 0,
                RiskTier.MEDIUM.value: 0,
                RiskTier.HIGH.value: 0,
            }
            for r in Region
        }

        # Initialize total counts from all registered suppliers
        for s in suppliers:
            if s.tier in tier_stats:
                tier_stats[s.tier]["total"] += 1
            if s.region in reg_stats:
                reg_stats[s.region]["total"] += 1

        # 2. Fetch all attestations for the year
        att_stmt = select(AttestationCycleModel).where(AttestationCycleModel.cycle_year == cycle_year)
        att_res = await self.db.execute(att_stmt)
        attestations = list(att_res.scalars().all())

        evaluated_statuses = {
            AttestationStatus.SUBMITTED.value,
            AttestationStatus.NORMALIZED.value,
            AttestationStatus.UNDER_REVIEW.value,
            AttestationStatus.APPROVED.value,
            AttestationStatus.FOLLOW_UP_REQUIRED.value,
            AttestationStatus.CLOSED.value,
        }

        submitted_count = sum(
            1 for a in attestations
            if a.status in evaluated_statuses
        )
        attestation_rate = round((submitted_count / total_invited * 100.0) if total_invited > 0 else 0.0, 1)

        # 3. Fetch all assessments
        ass_stmt = (
            select(AssessmentModel, AttestationCycleModel, SupplierModel)
            .join(AttestationCycleModel, AssessmentModel.attestation_id == AttestationCycleModel.id)
            .join(SupplierModel, AttestationCycleModel.supplier_id == SupplierModel.id)
            .where(AttestationCycleModel.cycle_year == cycle_year)
        )
        ass_res = await self.db.execute(ass_stmt)
        assessment_rows = list(ass_res.all())

        risk_counts = {
            RiskTier.CRITICAL.value: 0,
            RiskTier.HIGH.value: 0,
            RiskTier.MEDIUM.value: 0,
            RiskTier.LOW.value: 0,
        }
        env_scores: list[float] = []
        soc_scores: list[float] = []
        gov_scores: list[float] = []

        for ass, att, sup in assessment_rows:
            tier_val = sup.tier
            reg_val = sup.region
            r_tier = ass.risk_tier

            risk_counts[r_tier] = risk_counts.get(r_tier, 0) + 1
            env_scores.append(ass.environmental_score)
            soc_scores.append(ass.social_score)
            gov_scores.append(ass.governance_score)

            if tier_val in tier_stats and r_tier in tier_stats[tier_val]:
                tier_stats[tier_val][r_tier] += 1

            if reg_val in reg_stats:
                if r_tier in [RiskTier.LOW.value, RiskTier.MEDIUM.value]:
                    reg_stats[reg_val][r_tier] += 1
                else:
                    reg_stats[reg_val][RiskTier.HIGH.value] += 1

        total_assessed = len(assessment_rows)
        risk_breakdown = [
            RiskDistributionItem(
                category=cat,
                count=cnt,
                percentage=round((cnt / total_assessed * 100.0) if total_assessed > 0 else 0.0, 1)
            )
            for cat, cnt in risk_counts.items()
        ]

        pillar_averages = PillarAverageScores(
            environmental_avg=round(sum(env_scores) / len(env_scores), 1) if env_scores else 0.0,
            social_avg=round(sum(soc_scores) / len(soc_scores), 1) if soc_scores else 0.0,
            governance_avg=round(sum(gov_scores) / len(gov_scores), 1) if gov_scores else 0.0,
            overall_compliance_avg=round(
                (sum(env_scores) + sum(soc_scores) + sum(gov_scores)) / (len(env_scores) * 3), 1
            ) if env_scores else 0.0
        )

        tier_distribution = [
            TierRiskData(
                tier=SupplierTier(t),
                total_suppliers=tier_stats[t]["total"],
                low_risk=tier_stats[t][RiskTier.LOW.value],
                medium_risk=tier_stats[t][RiskTier.MEDIUM.value],
                high_risk=tier_stats[t][RiskTier.HIGH.value],
                critical_risk=tier_stats[t][RiskTier.CRITICAL.value],
            )
            for t in tier_stats
        ]

        regional_distribution = [
            RegionalRiskData(
                region=Region(r),
                total_suppliers=reg_stats[r]["total"],
                low_risk=reg_stats[r][RiskTier.LOW.value],
                medium_risk=reg_stats[r][RiskTier.MEDIUM.value],
                high_risk=reg_stats[r][RiskTier.HIGH.value],
            )
            for r in reg_stats
        ]

        # Top recurring shortfalls
        find_stmt = select(FindingModel)
        find_res = await self.db.execute(find_stmt)
        all_findings = list(find_res.scalars().all())

        finding_counts = Counter(f.standard_clause for f in all_findings)
        top_shortfalls = []
        for clause, count in finding_counts.most_common(5):
            match_f = next(f for f in all_findings if f.standard_clause == clause)
            top_shortfalls.append(TopFindingShortfall(
                standard_clause=clause,
                pillar=match_f.pillar,
                occurrence_count=count,
                severity=match_f.severity
            ))

        prog_risk = (
            RiskTier.HIGH.value if risk_counts.get(RiskTier.CRITICAL.value, 0) + risk_counts.get(RiskTier.HIGH.value, 0) > total_assessed * 0.4
            else RiskTier.MEDIUM.value if risk_counts.get(RiskTier.MEDIUM.value, 0) > total_assessed * 0.3
            else RiskTier.LOW.value
        )

        narrative = TemplateRenderer.render(
            "executive_report.md.j2",
            cycle_year=cycle_year,
            total_invited=total_invited,
            submitted_count=submitted_count,
            attestation_rate=attestation_rate,
            prog_risk=prog_risk,
            pillar_averages=pillar_averages,
            top_shortfalls=top_shortfalls,
        )

        return ProgrammeReportResponse(
            cycle_year=cycle_year,
            total_suppliers_invited=total_invited,
            responses_submitted=submitted_count,
            attestation_rate_pct=attestation_rate,
            overall_programme_risk_level=prog_risk,
            pillar_averages=pillar_averages,
            risk_tier_breakdown=risk_breakdown,
            tier_distribution=tier_distribution,
            regional_distribution=regional_distribution,
            top_recurring_shortfalls=top_shortfalls,
            executive_narrative_markdown=narrative,
            generated_at=datetime.now(timezone.utc).isoformat()
        )
