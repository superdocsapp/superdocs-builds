import re
import uuid
from typing import List, Tuple
from app.helpers.text_extractor import extract_verbatim_quote
from app.schemas.assessment import SocialMetrics, FindingSchema
from app.schemas.enums import ESGPillar, FindingSeverity


class SocialEvaluator:
    """Evaluates labor, working hours, and human rights standards against ILO frameworks."""

    @staticmethod
    def evaluate(raw_text: str, region: str) -> Tuple[SocialMetrics, List[FindingSchema]]:
        lower_text = raw_text.lower()
        findings: List[FindingSchema] = []
        soc = SocialMetrics()

        # Working Hours & Overtime
        hours_match = re.search(r"(\d+)\s*(?:hours|hrs)\s*(?:per\s*week|weekly)", lower_text)
        if hours_match:
            soc.maximum_weekly_hours = int(hours_match.group(1))

        # Forced Labor Prohibition
        if "forced labor" in lower_text and ("prohibit" in lower_text or "ban" in lower_text or "zero" in lower_text):
            soc.forced_labor_prohibition = True

        # Child Labor Prohibition
        if "child labor" in lower_text and ("prohibit" in lower_text or "ban" in lower_text or "zero" in lower_text):
            soc.child_labor_prohibition = True

        # Grievance Mechanism
        if "grievance" in lower_text and ("hotline" in lower_text or "box" in lower_text or "channel" in lower_text or "active" in lower_text):
            soc.worker_grievance_mechanism = True

        # Gap Finding: Excessive weekly hours (>60 hrs/week)
        if soc.maximum_weekly_hours > 60:
            quote = extract_verbatim_quote(
                raw_text,
                ["overtime", "peak season", f"{soc.maximum_weekly_hours} hours", "working hours"],
                f"During peak production seasons, workers operate up to {soc.maximum_weekly_hours} hours per week to meet quota deadlines."
            )
            findings.append(FindingSchema(
                id=str(uuid.uuid4()),
                pillar=ESGPillar.SOCIAL,
                severity=FindingSeverity.CRITICAL,
                standard_clause="Clause 2.3: Maximum Statutory Working Hours & Rest Day Guarantee",
                shortfall_summary=f"Reported working hours of {soc.maximum_weekly_hours} hrs/week exceed maximum international ILO limit of 60 hours (including overtime).",
                supplier_exact_quote=quote,
                source_location="Labor & Working Hours Disclosure",
                recommended_action="Implement mandatory shift capping at 60 hours/week and institute guaranteed weekly rest days."
            ))

        # Gap Finding: Recruitment fee deductions in APAC / Global supply chain
        if ("recruitment" in lower_text and "fee" in lower_text) and ("deduct" in lower_text or "agency" in lower_text) and "reimburse" not in lower_text and "zero" not in lower_text:
            quote = extract_verbatim_quote(
                raw_text,
                ["recruitment", "agency fee", "agency fees", "placement"],
                "Recruitment agency fees are deducted across the first 6 months of employment."
            )
            findings.append(FindingSchema(
                id=str(uuid.uuid4()),
                pillar=ESGPillar.SOCIAL,
                severity=FindingSeverity.CRITICAL,
                standard_clause="Clause APAC-1: Employer-Pays Principle & Recruitment Fee Prohibition",
                shortfall_summary="Supplier permits recruitment fee deductions from worker wages in violation of the Employer-Pays Principle.",
                supplier_exact_quote=quote,
                source_location="Annex R-APAC Section 1",
                recommended_action="Abolish all worker wage deductions for agency fees and initiate immediate reimbursement to affected workers."
            ))

        return soc, findings
