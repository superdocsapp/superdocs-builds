from pydantic import BaseModel, Field
from typing import List, Optional

class Milestone(BaseModel):
    id: str = Field(..., description="Unique identifier e.g. MS-01")
    description: str = Field(..., description="Milestone description")
    target_date: str = Field(..., description="Target completion date YYYY-MM-DD")
    status: str = Field(..., description="Status: Completed, In Progress, Delayed, Not Started")
    movement_since_last_period: Optional[str] = Field(None, description="Movement description relative to previous report")

class WorkstreamStatus(BaseModel):
    name: str = Field(..., description="Workstream name e.g. Workstream A (Frontend)")
    lead: Optional[str] = Field(None, description="Workstream lead name")
    status: str = Field(..., description="Status badge: GREEN, AMBER, RED")
    highlights: List[str] = Field(default_factory=list, description="Key achievements in this period")
    reasons_and_blockers: Optional[str] = Field(None, description="Explanation for AMBER/RED status or delays")
    movement_since_last_period: Optional[str] = Field(None, description="Trajectory shift e.g. Upgraded GREEN -> AMBER")

class RiskItem(BaseModel):
    id: str = Field(..., description="Unique identifier e.g. RISK-01 or ISSUE-01")
    item_type: str = Field("RISK", description="Type: RISK or ISSUE")
    description: str = Field(..., description="Risk or Issue summary")
    severity: str = Field(..., description="Severity: High, Medium, Low")
    status: str = Field("Open", description="Status: Open, Closed, Resolved")
    impact: Optional[str] = Field(None, description="Project impact")
    mitigation: Optional[str] = Field(None, description="Mitigation or action plan")
    movement_since_last_period: Optional[str] = Field(None, description="Delta statement since last period")

class FinancialState(BaseModel):
    total_approved_budget: float = Field(..., description="Total approved budget in USD")
    cumulative_spend: float = Field(..., description="Cumulative spend to date in USD")
    remaining_budget: float = Field(..., description="Remaining budget in USD")
    burn_rate_percent: float = Field(..., description="Percentage of total budget consumed")
    status: str = Field("GREEN", description="Financial health: GREEN, AMBER, RED")
    workstream_breakdown: Optional[dict] = Field(None, description="Spend breakdown by workstream")
    movement_since_last_period: Optional[str] = Field(None, description="Budget burn delta since last period")

class DecisionNeeded(BaseModel):
    id: str = Field(..., description="Unique decision ID e.g. DEC-01")
    topic: str = Field(..., description="Decision summary")
    impact: str = Field(..., description="Why decision is needed")
    owner: str = Field(..., description="Decision maker or body")

class ProjectState(BaseModel):
    period_name: str = Field(..., description="Period identifier e.g. July 2026 / Period 1")
    project_name: str = Field("Project Catalyst", description="Project title")
    overall_status: str = Field("GREEN", description="Overall project status: GREEN, AMBER, RED")
    executive_summary: str = Field("", description="Executive summary overview")
    milestones: List[Milestone] = Field(default_factory=list)
    workstreams: List[WorkstreamStatus] = Field(default_factory=list)
    risks_and_issues: List[RiskItem] = Field(default_factory=list)
    financials: Optional[FinancialState] = None
    decisions_needed: List[DecisionNeeded] = Field(default_factory=list)
