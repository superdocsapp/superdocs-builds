"""
State Comparison & Movement Engine
Derives deterministic "since last period" movement statements by comparing previous and current ProjectState.
"""
from typing import Dict, Any, List, Tuple
from app.models import ProjectState, Milestone, WorkstreamStatus, RiskItem, FinancialState

class StateComparator:
    """Compares previous and current ProjectState objects to compute period-over-period movements."""

    def compare_states(self, previous: ProjectState, current: ProjectState) -> ProjectState:
        """
        Takes previous period state and current period state, compares all entities,
        and returns updated current state with populated 'movement_since_last_period' fields.
        """
        # Create a deep copy or updated state object
        updated_current = current.model_copy(deep=True)

        # 1. Milestone movements
        prev_ms_map = {m.id: m for m in previous.milestones}
        for ms in updated_current.milestones:
            prev_ms = prev_ms_map.get(ms.id)
            if not prev_ms:
                ms.movement_since_last_period = "New milestone added in current period."
            else:
                movements = []
                if prev_ms.status != ms.status:
                    movements.append(f"Status changed from {prev_ms.status} to {ms.status}")
                if prev_ms.target_date != ms.target_date:
                    movements.append(f"Target date shifted from {prev_ms.target_date} to {ms.target_date}")
                
                if movements:
                    ms.movement_since_last_period = "; ".join(movements)
                else:
                    ms.movement_since_last_period = "Unchanged since last period"

        # 2. Workstream status trajectory shifts
        prev_ws_map = {w.name.split()[0].lower(): w for w in previous.workstreams}
        for ws in updated_current.workstreams:
            ws_key = ws.name.split()[0].lower()
            prev_ws = prev_ws_map.get(ws_key)
            if not prev_ws:
                ws.movement_since_last_period = "New workstream initialized."
            else:
                if prev_ws.status != ws.status:
                    if ws.status == "RED":
                        direction = "Downgraded to RED"
                    elif ws.status == "AMBER" and prev_ws.status == "GREEN":
                        direction = "Shifted GREEN -> AMBER"
                    elif ws.status == "GREEN" and prev_ws.status == "AMBER":
                        direction = "Upgraded AMBER -> GREEN"
                    else:
                        direction = f"Status shifted {prev_ws.status} -> {ws.status}"
                    ws.movement_since_last_period = direction
                else:
                    ws.movement_since_last_period = f"Maintained {ws.status} status"

        # 3. Risk & Issue movements
        prev_risk_map = {r.id: r for r in previous.risks_and_issues}
        curr_risk_ids = {r.id for r in updated_current.risks_and_issues}

        for r in updated_current.risks_and_issues:
            prev_r = prev_risk_map.get(r.id)
            if not prev_r:
                r.movement_since_last_period = f"NEW {r.item_type} identified in this period."
            else:
                changes = []
                if prev_r.severity != r.severity:
                    changes.append(f"Severity shifted from {prev_r.severity} to {r.severity}")
                if prev_r.item_type != r.item_type:
                    changes.append(f"Converted from {prev_r.item_type} to {r.item_type}")
                if prev_r.status != r.status:
                    changes.append(f"Status changed from {prev_r.status} to {r.status}")

                if changes:
                    r.movement_since_last_period = "; ".join(changes)
                else:
                    r.movement_since_last_period = "No severity or status change"

        # Detect closed/resolved risks from previous period not present in current active list
        for prev_id, prev_r in prev_risk_map.items():
            if prev_id not in curr_risk_ids:
                closed_r = prev_r.model_copy(deep=True)
                closed_r.status = "Resolved"
                closed_r.movement_since_last_period = f"RESOLVED in current period (was {prev_r.severity} {prev_r.item_type})."
                updated_current.risks_and_issues.append(closed_r)

        # 4. Financial burn & spend movement
        if updated_current.financials and previous.financials:
            pf = previous.financials
            cf = updated_current.financials
            spend_diff = cf.cumulative_spend - pf.cumulative_spend
            burn_diff = round(cf.burn_rate_percent - pf.burn_rate_percent, 1)

            fin_notes = []
            if spend_diff > 0:
                fin_notes.append(f"Spend increased by ${spend_diff:,.2f} since last period")
            fin_notes.append(f"Burn rate changed from {pf.burn_rate_percent}% to {cf.burn_rate_percent}% (+{burn_diff}%)")
            if pf.status != cf.status:
                fin_notes.append(f"Financial health shifted {pf.status} -> {cf.status}")

            cf.movement_since_last_period = "; ".join(fin_notes)

        # 5. Overall status shift
        if previous.overall_status != updated_current.overall_status:
            updated_current.executive_summary += f"\n\n**Period Movement**: Overall project health status shifted from {previous.overall_status} to {updated_current.overall_status}."

        return updated_current
