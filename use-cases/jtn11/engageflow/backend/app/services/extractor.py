"""
Document State Extraction Engine
Parses project document collections into normalized ProjectState objects.
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Union
from app.models import ProjectState, Milestone, WorkstreamStatus, RiskItem, FinancialState, DecisionNeeded

class DocumentExtractor:
    """Extracts structured ProjectState from raw document files or content strings."""

    def extract_from_folder(self, folder_path: Path, period_name: str) -> ProjectState:
        """Reads all markdown files in a period folder and constructs a unified ProjectState."""
        docs = {}
        for md_file in folder_path.glob("*.md"):
            docs[md_file.name] = md_file.read_text(encoding="utf-8")

        return self.extract_from_docs_dict(docs, period_name)

    def extract_from_docs_dict(self, docs: Dict[str, str], period_name: str) -> ProjectState:
        milestones = self._parse_project_plan(docs.get("Project_Plan.md", ""))
        risks_and_issues = self._parse_risk_log(docs.get("Risk_Issue_Log.md", ""))
        financials = self._parse_financials(docs.get("Financial_Report.md", ""))
        workstreams = []

        for fname, content in docs.items():
            if fname.startswith("Workstream_") and fname.endswith("_Update.md"):
                ws = self._parse_workstream_update(fname, content)
                if ws:
                    workstreams.append(ws)

        workstreams.sort(key=lambda x: x.name)

        overall_status = "GREEN"
        if any(w.status == "RED" for w in workstreams) or (financials and financials.status == "RED"):
            overall_status = "RED"
        elif any(w.status == "AMBER" for w in workstreams) or (financials and financials.status == "AMBER"):
            overall_status = "AMBER"

        return ProjectState(
            period_name=period_name,
            project_name="Project Catalyst",
            overall_status=overall_status,
            executive_summary=f"Project Catalyst update for {period_name}.",
            milestones=milestones,
            workstreams=workstreams,
            risks_and_issues=risks_and_issues,
            financials=financials,
            decisions_needed=[]
        )

    def _parse_project_plan(self, content: str) -> List[Milestone]:
        milestones = []
        lines = content.splitlines()
        for line in lines:
            if line.startswith("| MS-"):
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 4:
                    ms_id = parts[0]
                    desc = parts[1]
                    target_date = parts[2]
                    status = parts[4] if len(parts) >= 5 else parts[3]
                    milestones.append(Milestone(
                        id=ms_id,
                        description=desc,
                        target_date=target_date,
                        status=status
                    ))
        return milestones

    def _parse_risk_log(self, content: str) -> List[RiskItem]:
        items = []
        current_item: Optional[dict] = None

        lines = content.splitlines()
        for line in lines:
            line_str = line.strip()
            if line_str.startswith("- **RISK-") or line_str.startswith("- **ISSUE-"):
                if current_item:
                    items.append(RiskItem(**current_item))
                
                is_issue = line_str.startswith("- **ISSUE-")
                item_id = line_str.split("**")[1].split(":")[0].strip()
                desc = line_str.split(":", 1)[1].strip() if ":" in line_str else line_str

                current_item = {
                    "id": item_id,
                    "item_type": "ISSUE" if is_issue else "RISK",
                    "description": desc,
                    "severity": "Medium",
                    "status": "Open",
                    "impact": "",
                    "mitigation": ""
                }
            elif current_item and "Severity" in line_str:
                sev_text = line_str.split(":", 1)[1].strip() if ":" in line_str else line_str
                sev = sev_text.split("(")[0].strip()
                current_item["severity"] = sev
            elif current_item and "Status" in line_str:
                current_item["status"] = line_str.split(":", 1)[1].strip() if ":" in line_str else line_str
            elif current_item and "Impact" in line_str:
                current_item["impact"] = line_str.split(":", 1)[1].strip() if ":" in line_str else line_str
            elif current_item and "Mitigation" in line_str:
                current_item["mitigation"] = line_str.split(":", 1)[1].strip() if ":" in line_str else line_str

        if current_item:
            items.append(RiskItem(**current_item))

        return items

    def _parse_financials(self, content: str) -> Optional[FinancialState]:
        if not content:
            return None

        total_budget = 150000.0
        cumulative_spend = 0.0
        remaining_budget = 150000.0
        burn_rate = 0.0
        status = "GREEN"

        for line in content.splitlines():
            line_str = line.strip()
            if "Total Approved Budget" in line_str:
                val = re.sub(r"[^\d.]", "", line_str.split(":")[-1])
                if val: total_budget = float(val)
            elif "Cumulative Actual Spend" in line_str:
                val = re.sub(r"[^\d.]", "", line_str.split(":")[-1])
                if val: cumulative_spend = float(val)
            elif "Remaining Budget" in line_str:
                val = re.sub(r"[^\d.]", "", line_str.split(":")[-1])
                if val: remaining_budget = float(val)
            elif "Budget Burn Rate" in line_str:
                val = re.sub(r"[^\d.]", "", line_str.split(":")[-1])
                if val: burn_rate = float(val)
            elif "Financial Health" in line_str:
                status_raw = line_str.split(":")[-1].strip()
                if "RED" in status_raw: status = "RED"
                elif "AMBER" in status_raw: status = "AMBER"

        if burn_rate == 0.0 and total_budget > 0:
            burn_rate = round((cumulative_spend / total_budget) * 100, 1)

        return FinancialState(
            total_approved_budget=total_budget,
            cumulative_spend=cumulative_spend,
            remaining_budget=remaining_budget,
            burn_rate_percent=burn_rate,
            status=status
        )

    def _parse_workstream_update(self, filename: str, content: str) -> Optional[WorkstreamStatus]:
        lines = content.splitlines()
        ws_name = filename.replace("_Update.md", "").replace("_", " ")
        if lines and lines[0].startswith("# Workstream"):
            ws_name = lines[0].replace("# ", "").split("(")[0].strip()

        status = "GREEN"
        lead = "TBD"
        highlights = []
        reason = ""

        in_highlights = False

        for line in lines:
            line_str = line.strip()
            if "Status" in line_str and ("GREEN" in line_str or "AMBER" in line_str or "RED" in line_str):
                raw_stat = line_str.split(":")[-1].strip()
                if "RED" in raw_stat: status = "RED"
                elif "AMBER" in raw_stat: status = "AMBER"
                elif "GREEN" in raw_stat: status = "GREEN"
            elif "Lead" in line_str and ":" in line_str:
                lead = line_str.split(":")[-1].strip()
            elif "Highlights" in line_str:
                in_highlights = True
                continue
            elif "Next Steps" in line_str or "Reason" in line_str or "Key Reason" in line_str:
                in_highlights = False

            if in_highlights and (line_str.startswith("- ") or line_str.startswith("  - ") or line_str.startswith("* ")):
                bullet = line_str.lstrip("- *").strip()
                if bullet and not bullet.startswith("Highlights"):
                    highlights.append(bullet)

            if "Key Reason" in line_str or "Reason for" in line_str:
                reason = line_str.split(":", 1)[-1].strip() if ":" in line_str else line_str

        return WorkstreamStatus(
            name=ws_name,
            lead=lead,
            status=status,
            highlights=highlights,
            reasons_and_blockers=reason if reason else None
        )
