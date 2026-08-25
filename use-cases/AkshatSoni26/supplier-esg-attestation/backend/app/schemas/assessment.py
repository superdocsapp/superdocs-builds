from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.enums import ESGPillar, FindingSeverity, ReviewDecision, RiskTier


class EnvironmentalMetrics(BaseModel):
    ghg_scope_1_reported: bool = False
    ghg_scope_1_mt_co2e: float | None = None
    ghg_scope_2_reported: bool = False
    ghg_scope_2_mt_co2e: float | None = None
    ghg_scope_3_tracked: bool = False
    renewable_energy_percentage: float = 0.0
    iso_14001_certified: bool = False
    waste_diversion_rate: float = 0.0
    hazardous_waste_compliant: bool = True
    water_stewardship_plan: bool = False


class SocialMetrics(BaseModel):
    forced_labor_prohibition: bool = True
    child_labor_prohibition: bool = True
    maximum_weekly_hours: int = 48
    living_wage_guarantee: bool = True
    iso_45001_or_ohsas_certified: bool = False
    worker_grievance_mechanism: bool = True
    freedom_of_association: bool = True
    migrant_worker_protections: bool = True


class GovernanceMetrics(BaseModel):
    anti_bribery_policy: bool = True
    whistleblower_protection_channel: bool = True
    board_esg_oversight: bool = False
    sub_tier_traceability: bool = False
    iso_27001_cyber_compliance: bool = False
    code_of_conduct_signed: bool = True


class FindingSchema(BaseModel):
    id: str
    pillar: ESGPillar
    severity: FindingSeverity
    standard_clause: str
    shortfall_summary: str
    supplier_exact_quote: str
    source_location: str | None = None
    recommended_action: str
    review_decision: ReviewDecision = ReviewDecision.PENDING
    review_notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


class FindingReviewUpdate(BaseModel):
    finding_id: str
    review_decision: ReviewDecision
    review_notes: str | None = None


class NormalizedAssessmentSchema(BaseModel):
    environmental: EnvironmentalMetrics
    social: SocialMetrics
    governance: GovernanceMetrics
    environmental_score: float = Field(..., ge=0.0, le=100.0)
    social_score: float = Field(..., ge=0.0, le=100.0)
    governance_score: float = Field(..., ge=0.0, le=100.0)
    overall_risk_score: float = Field(..., ge=0.0, le=100.0)  # Lower is safer, higher is higher risk
    risk_tier: RiskTier
    executive_summary: str
    findings: list[FindingSchema] = []


class AssessmentResponse(BaseModel):
    id: str
    attestation_id: str
    overall_risk_score: float
    risk_tier: RiskTier
    environmental_score: float
    social_score: float
    governance_score: float
    summary_markdown: str | None = None
    is_approved: bool = False
    approved_by: str | None = None
    approved_at: datetime | None = None
    findings: list[FindingSchema] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AssessmentReviewRequest(BaseModel):
    is_approved: bool
    approved_by: str
    finding_decisions: list[FindingReviewUpdate] = []
