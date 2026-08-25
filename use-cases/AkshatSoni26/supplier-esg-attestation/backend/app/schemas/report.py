from datetime import datetime, timezone
from pydantic import BaseModel, Field
from app.schemas.enums import SupplierTier, Region


class RiskDistributionItem(BaseModel):
    category: str
    count: int
    percentage: float


class PillarAverageScores(BaseModel):
    environmental_avg: float
    social_avg: float
    governance_avg: float
    overall_compliance_avg: float


class TierRiskData(BaseModel):
    tier: SupplierTier
    total_suppliers: int
    low_risk: int
    medium_risk: int
    high_risk: int
    critical_risk: int


class RegionalRiskData(BaseModel):
    region: Region
    total_suppliers: int
    low_risk: int
    medium_risk: int
    high_risk: int


class TopFindingShortfall(BaseModel):
    standard_clause: str
    pillar: str
    occurrence_count: int
    severity: str


class ProgrammeReportResponse(BaseModel):
    cycle_year: int
    total_suppliers_invited: int
    responses_submitted: int
    attestation_rate_pct: float
    overall_programme_risk_level: str
    pillar_averages: PillarAverageScores
    risk_tier_breakdown: list[RiskDistributionItem]
    tier_distribution: list[TierRiskData]
    regional_distribution: list[RegionalRiskData]
    top_recurring_shortfalls: list[TopFindingShortfall]
    executive_narrative_markdown: str
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
