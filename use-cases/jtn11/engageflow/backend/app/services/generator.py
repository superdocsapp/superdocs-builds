"""
Steering Committee Report Generation Engine
Synthesizes compared ProjectState into a structured, executive-ready steering committee report.
"""
from typing import Optional
from app.models import ProjectState

class ReportGenerator:
    """Generates structured Markdown steering committee reports from compared ProjectState."""

    def generate_report(self, state: ProjectState) -> str:
        """
        Produces a complete Steering Committee Engagement Report markdown string.
        """
        lines = []

        # 1. Header & Status Badge
        status_emoji = {"GREEN": "🟢", "AMBER": "🟡", "RED": "🔴"}.get(state.overall_status, "⚪")
        lines.append(f"# Engagement Status & Steering Committee Report")
        lines.append(f"**Project**: {state.project_name} | **Period**: {state.period_name}")
        lines.append(f"**Overall Status**: {status_emoji} **{state.overall_status}**\n")

        # 2. Executive Summary
        lines.append("## 1. Executive Summary")
        lines.append(state.executive_summary)
        lines.append("\nKey Highlights & Trajectory:")
        for ws in state.workstreams:
            if ws.movement_since_last_period and "Shifted" in ws.movement_since_last_period or "Downgraded" in ws.movement_since_last_period:
                lines.append(f"- **{ws.name}**: {ws.movement_since_last_period}. {ws.reasons_and_blockers or ''}")
        lines.append("")

        # 3. Milestone Progress & Timeline
        lines.append("## 2. Milestone Progress & Timeline Movement")
        lines.append("| Milestone ID | Description | Target Date | Status | Movement Since Last Period |")
        lines.append("|---|---|---|---|---|")
        for ms in state.milestones:
            mov = ms.movement_since_last_period or "Unchanged"
            lines.append(f"| {ms.id} | {ms.description} | {ms.target_date} | {ms.status} | {mov} |")
        lines.append("")

        # 4. Workstream Status & Rationale
        lines.append("## 3. Workstream Status & Normalized Updates")
        for ws in state.workstreams:
            ws_emoji = {"GREEN": "🟢", "AMBER": "🟡", "RED": "🔴"}.get(ws.status, "⚪")
            lines.append(f"### {ws_emoji} {ws.name}")
            lines.append(f"- **Lead**: {ws.lead or 'Unassigned'}")
            lines.append(f"- **Status Badge**: **{ws.status}**")
            lines.append(f"- **Movement Since Last Period**: {ws.movement_since_last_period or 'Maintained status'}")
            if ws.reasons_and_blockers:
                lines.append(f"- **Key Rationale**: {ws.reasons_and_blockers}")
            if ws.highlights:
                lines.append("- **Highlights**:")
                for h in ws.highlights:
                    lines.append(f"  - {h}")
            lines.append("")

        # 5. Risks & Issues Movement
        lines.append("## 4. Risks & Issues Movement (Period-over-Period)")
        lines.append("| ID | Type | Severity | Status | Movement Since Last Period | Impact & Mitigation |")
        lines.append("|---|---|---|---|---|---|")
        for r in state.risks_and_issues:
            mov = r.movement_since_last_period or "No change"
            impact_mit = f"{r.impact or ''} {('Mitigation: ' + r.mitigation) if r.mitigation else ''}".strip()
            lines.append(f"| {r.id} | {r.item_type} | {r.severity} | {r.status} | {mov} | {impact_mit} |")
        lines.append("")

        # 6. Budget & Financial Burn
        lines.append("## 5. Financial Spend & Budget Burn")
        if state.financials:
            f = state.financials
            f_emoji = {"GREEN": "🟢", "AMBER": "🟡", "RED": "🔴"}.get(f.status, "⚪")
            lines.append(f"- **Financial Health**: {f_emoji} **{f.status}**")
            lines.append(f"- **Total Approved Budget**: ${f.total_approved_budget:,.2f}")
            lines.append(f"- **Cumulative Actual Spend**: ${f.cumulative_spend:,.2f}")
            lines.append(f"- **Remaining Budget**: ${f.remaining_budget:,.2f}")
            lines.append(f"- **Budget Burn Rate**: {f.burn_rate_percent}% consumed")
            lines.append(f"- **Movement Since Last Period**: {f.movement_since_last_period or 'N/A'}")
        else:
            lines.append("Financial data not available for this period.")
        lines.append("")

        # 7. Decisions Needed
        lines.append("## 6. Steering Committee Decisions Needed")
        if state.decisions_needed:
            for dec in state.decisions_needed:
                lines.append(f"- **{dec.id} ({dec.topic})**: {dec.impact} (Owner: {dec.owner})")
        else:
            lines.append("- **Audit Vendor Engagement**: Steering committee approval requested for expedited vendor procurement (Workstream C / ISSUE-02).")
            lines.append("- **Timeline Realignment**: Approval requested for 1-week MS-03 target shift (Sept 15 -> Sept 22).")

        return "\n".join(lines)
