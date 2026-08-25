"""Isolated unit tests for modular ESG evaluators and scoring calculator."""
from app.services.evaluators import (
    EnvironmentalEvaluator,
    SocialEvaluator,
    GovernanceEvaluator,
    ESGScoringCalculator,
)
from app.schemas.enums import ESGPillar, FindingSeverity, RiskTier, SupplierTier, Region
from app.schemas.assessment import EnvironmentalMetrics, SocialMetrics, GovernanceMetrics, FindingSchema


class TestEnvironmentalEvaluator:
    def test_tier1_missing_scope2_produces_high_finding(self):
        text = "Scope 1 emissions: 500 mt CO2e. We do not measure Scope 2 emissions."
        env, findings = EnvironmentalEvaluator.evaluate(text, tier=SupplierTier.TIER_1_STRATEGIC.value)
        assert env.ghg_scope_1_reported is True
        assert env.ghg_scope_2_reported is False
        assert len(findings) == 2  # Missing Scope 2 + Missing ISO 14001
        assert any(f.pillar == ESGPillar.ENVIRONMENTAL and f.severity == FindingSeverity.HIGH for f in findings)

    def test_tier3_missing_iso14001_no_finding_penalty(self):
        text = "Scope 1 emissions: 100 mt CO2e. Scope 2 emissions: 50 mt CO2e."
        env, findings = EnvironmentalEvaluator.evaluate(text, tier=SupplierTier.TIER_3_COMMODITY.value)
        # Tier 3 doesn't mandate ISO 14001
        assert len(findings) == 0


class TestSocialEvaluator:
    def test_overtime_violation_produces_critical_finding(self):
        text = "During peak season, employees work 72 hours per week."
        soc, findings = SocialEvaluator.evaluate(text, region=Region.APAC.value)
        assert soc.maximum_weekly_hours == 72
        assert len(findings) >= 1
        critical = [f for f in findings if f.severity == FindingSeverity.CRITICAL]
        assert len(critical) >= 1
        assert "72 hrs/week exceed maximum international ILO limit" in critical[0].shortfall_summary

    def test_recruitment_fee_violation(self):
        text = "Recruitment agency fees are deducted across first 6 months of employment."
        soc, findings = SocialEvaluator.evaluate(text, region=Region.APAC.value)
        assert any("Employer-Pays Principle" in f.standard_clause for f in findings)


class TestGovernanceEvaluator:
    def test_anti_bribery_missing_produces_high_finding(self):
        text = "Formal anti-corruption training is currently informal and not documented."
        gov, findings = GovernanceEvaluator.evaluate(text, tier=SupplierTier.TIER_1_STRATEGIC.value)
        assert gov.anti_bribery_policy is False
        assert len(findings) == 1
        assert findings[0].pillar == ESGPillar.GOVERNANCE
        assert findings[0].severity == FindingSeverity.HIGH


class TestESGScoringCalculator:
    def test_perfect_compliance_honest_zero_findings(self):
        env = EnvironmentalMetrics(
            ghg_scope_1_reported=True,
            ghg_scope_2_reported=True,
            ghg_scope_3_tracked=True,
            iso_14001_certified=True,
            renewable_energy_percentage=100.0,
        )
        soc = SocialMetrics(
            maximum_weekly_hours=40,
            forced_labor_prohibition=True,
            child_labor_prohibition=True,
            living_wage_guarantee=True,
            worker_grievance_mechanism=True,
        )
        gov = GovernanceMetrics(
            anti_bribery_policy=True,
            whistleblower_protection_channel=True,
            sub_tier_traceability=True,
        )
        env_s, soc_s, gov_s, overall_risk, risk_tier, narrative = ESGScoringCalculator.calculate(
            env=env,
            soc=soc,
            gov=gov,
            findings=[],
            tier=SupplierTier.TIER_1_STRATEGIC.value,
            region=Region.EU.value,
            supplier_name="Nordic CleanTech AB",
        )
        assert env_s == 100.0
        assert soc_s == 100.0
        assert gov_s == 100.0
        assert overall_risk == 0.0
        assert risk_tier == RiskTier.LOW
        assert "Honest evaluation confirms 0 compliance shortfalls" in narrative
