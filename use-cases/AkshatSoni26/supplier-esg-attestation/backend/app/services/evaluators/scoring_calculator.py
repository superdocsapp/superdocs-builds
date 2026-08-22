from typing import List, Tuple
from app.schemas.assessment import (
    EnvironmentalMetrics,
    SocialMetrics,
    GovernanceMetrics,
    FindingSchema,
)
from app.schemas.enums import ESGPillar, FindingSeverity, RiskTier, SupplierTier


class ESGScoringCalculator:
    """Calculates weighted ESG pillar scores, aggregate risk indexes, risk tier classifications, and honest narratives."""

    @staticmethod
    def calculate(
        env: EnvironmentalMetrics,
        soc: SocialMetrics,
        gov: GovernanceMetrics,
        findings: List[FindingSchema],
        tier: str,
        region: str,
        supplier_name: str
    ) -> Tuple[float, float, float, float, RiskTier, str]:
        # --- 1. Environmental Score Calculation ---
        env_score = 100.0
        if not env.ghg_scope_1_reported:
            env_score -= 25.0
        if not env.ghg_scope_2_reported:
            env_score -= 25.0
        if not env.iso_14001_certified and tier != SupplierTier.TIER_3_COMMODITY.value:
            env_score -= 20.0
        if env.renewable_energy_percentage < 20.0:
            env_score -= 15.0
        env_score = max(10.0, env_score)

        # --- 2. Social Score Calculation ---
        soc_score = 100.0
        if soc.maximum_weekly_hours > 60:
            soc_score -= 40.0
        if not soc.worker_grievance_mechanism:
            soc_score -= 25.0
        if not soc.living_wage_guarantee:
            soc_score -= 25.0
        if any(f.pillar == ESGPillar.SOCIAL and f.severity == FindingSeverity.CRITICAL for f in findings):
            soc_score -= 20.0
        soc_score = max(10.0, soc_score)

        # --- 3. Governance Score Calculation ---
        gov_score = 100.0
        if not gov.anti_bribery_policy:
            gov_score -= 40.0
        if not gov.whistleblower_protection_channel:
            gov_score -= 30.0
        if not gov.sub_tier_traceability and tier == SupplierTier.TIER_1_STRATEGIC.value:
            gov_score -= 20.0
        gov_score = max(10.0, gov_score)

        # --- 4. Composite & Risk Tier Calculation ---
        compliance_composite = (env_score * 0.35) + (soc_score * 0.35) + (gov_score * 0.30)
        raw_risk = round(100.0 - compliance_composite, 1)

        critical_count = sum(1 for f in findings if f.severity == FindingSeverity.CRITICAL)
        high_count = sum(1 for f in findings if f.severity == FindingSeverity.HIGH)

        overall_risk_score = min(100.0, max(raw_risk, (critical_count * 25.0) + (high_count * 15.0) + raw_risk * 0.5))
        overall_risk_score = round(overall_risk_score, 1)

        if critical_count > 0 or overall_risk_score >= 60.0:
            risk_tier = RiskTier.CRITICAL
        elif high_count > 0 or overall_risk_score >= 40.0:
            risk_tier = RiskTier.HIGH
        elif overall_risk_score >= 20.0:
            risk_tier = RiskTier.MEDIUM
        else:
            risk_tier = RiskTier.LOW

        # --- 5. Honest Narrative Summary ---
        findings_count = len(findings)
        if findings_count > 0:
            exec_summary = (
                f"Supplier {supplier_name} completed the {tier} attestation cycle for jurisdiction {region}. "
                f"The assessment produced an Overall Risk Score of {overall_risk_score}/100 ({risk_tier.value}). "
                f"Pillar Scores: Environmental {env_score:.1f}%, Social {soc_score:.1f}%, Governance {gov_score:.1f}%. "
                f"Identified {findings_count} specific compliance findings requiring remediation."
            )
        else:
            exec_summary = (
                f"Supplier {supplier_name} completed the {tier} attestation cycle with an exceptional score. "
                f"Honest evaluation confirms 0 compliance shortfalls or discrepancies."
            )

        return env_score, soc_score, gov_score, overall_risk_score, risk_tier, exec_summary
