import time
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.logger import get_logger
from app.db.models import AttestationCycleModel, AssessmentModel, FindingModel, SupplierModel
from app.schemas.enums import AttestationStatus, ReviewDecision
from app.schemas.assessment import (
    FindingSchema,
    NormalizedAssessmentSchema,
)
from app.services.evaluators import (
    EnvironmentalEvaluator,
    SocialEvaluator,
    GovernanceEvaluator,
    ESGScoringCalculator,
)

logger = get_logger("normalization_service")


class NormalizationService:
    """
    Normalizes multi-format raw supplier responses into a unified assessment schema.
    Coordinates domain-specific evaluators (Environmental, Social, Governance) and persists results.
    """

    def __init__(self, db: AsyncSession | None = None):
        self.db = db

    def analyze_response_text(
        self,
        raw_text: str,
        tier: str,
        region: str,
        supplier_name: str
    ) -> NormalizedAssessmentSchema:
        """Runs modular evaluators across all three ESG pillars and calculates normalized scores."""
        all_findings: list[FindingSchema] = []

        # 1. Environmental Analysis
        env, env_findings = EnvironmentalEvaluator.evaluate(raw_text, tier=tier)
        all_findings.extend(env_findings)

        # 2. Social Analysis
        soc, soc_findings = SocialEvaluator.evaluate(raw_text, region=region)
        all_findings.extend(soc_findings)

        # 3. Governance Analysis
        gov, gov_findings = GovernanceEvaluator.evaluate(raw_text, tier=tier)
        all_findings.extend(gov_findings)

        # 4. Composite Scoring & Risk Classification
        (
            env_score,
            soc_score,
            gov_score,
            overall_risk_score,
            risk_tier,
            exec_summary,
        ) = ESGScoringCalculator.calculate(
            env=env,
            soc=soc,
            gov=gov,
            findings=all_findings,
            tier=tier,
            region=region,
            supplier_name=supplier_name,
        )

        return NormalizedAssessmentSchema(
            environmental=env,
            social=soc,
            governance=gov,
            environmental_score=env_score,
            social_score=soc_score,
            governance_score=gov_score,
            overall_risk_score=overall_risk_score,
            risk_tier=risk_tier,
            executive_summary=exec_summary,
            findings=all_findings,
        )

    async def normalize_attestation(self, attestation_id: str, raw_response_text: str) -> AssessmentModel:
        """Normalizes an attestation and commits assessment and finding records to DB."""
        t_start = time.monotonic()
        if not self.db:
            raise ValueError("Database session required for persistent normalization.")

        stmt = select(AttestationCycleModel).where(AttestationCycleModel.id == attestation_id)
        res = await self.db.execute(stmt)
        attestation = res.scalar_one_or_none()
        if not attestation:
            raise ValueError(f"Attestation {attestation_id} not found.")

        # Load supplier
        sup_stmt = select(SupplierModel).where(SupplierModel.id == attestation.supplier_id)
        sup_res = await self.db.execute(sup_stmt)
        supplier = sup_res.scalar_one_or_none()
        if not supplier:
            raise ValueError(f"Supplier for attestation {attestation_id} not found.")

        normalized_data = self.analyze_response_text(
            raw_response_text,
            tier=supplier.tier,
            region=supplier.region,
            supplier_name=supplier.name,
        )

        # Check for existing assessment
        ass_stmt = select(AssessmentModel).where(AssessmentModel.attestation_id == attestation.id)
        ass_res = await self.db.execute(ass_stmt)
        assessment = ass_res.scalar_one_or_none()

        if not assessment:
            assessment = AssessmentModel(
                id=str(uuid.uuid4()),
                attestation_id=attestation.id,
                overall_risk_score=normalized_data.overall_risk_score,
                risk_tier=normalized_data.risk_tier.value,
                environmental_score=normalized_data.environmental_score,
                social_score=normalized_data.social_score,
                governance_score=normalized_data.governance_score,
                summary_markdown=normalized_data.executive_summary,
                normalized_data_json=normalized_data.model_dump_json(),
                is_approved=False,
            )
            self.db.add(assessment)
            await self.db.flush()
        else:
            assessment.overall_risk_score = normalized_data.overall_risk_score
            assessment.risk_tier = normalized_data.risk_tier.value
            assessment.environmental_score = normalized_data.environmental_score
            assessment.social_score = normalized_data.social_score
            assessment.governance_score = normalized_data.governance_score
            assessment.summary_markdown = normalized_data.executive_summary
            assessment.normalized_data_json = normalized_data.model_dump_json()

        # Update findings
        del_stmt = select(FindingModel).where(FindingModel.assessment_id == assessment.id)
        del_res = await self.db.execute(del_stmt)
        for old_f in del_res.scalars():
            await self.db.delete(old_f)

        for f_schema in normalized_data.findings:
            new_finding = FindingModel(
                id=f_schema.id,
                assessment_id=assessment.id,
                pillar=f_schema.pillar.value,
                severity=f_schema.severity.value,
                standard_clause=f_schema.standard_clause,
                shortfall_summary=f_schema.shortfall_summary,
                supplier_exact_quote=f_schema.supplier_exact_quote,
                source_location=f_schema.source_location,
                recommended_action=f_schema.recommended_action,
                review_decision=ReviewDecision.PENDING.value,
            )
            self.db.add(new_finding)

        # Update attestation cycle status
        attestation.status = (
            AttestationStatus.FOLLOW_UP_REQUIRED.value
            if len(normalized_data.findings) > 0
            else AttestationStatus.NORMALIZED.value
        )
        attestation.normalized_at = datetime.now(timezone.utc)

        await self.db.commit()
        await self.db.refresh(assessment)

        elapsed = time.monotonic() - t_start
        logger.info(
            f"Normalization complete | attestation={attestation_id} "
            f"risk_tier={normalized_data.risk_tier.value} "
            f"findings={len(normalized_data.findings)} "
            f"risk_score={normalized_data.overall_risk_score} "
            f"elapsed={elapsed:.3f}s"
        )
        return assessment
