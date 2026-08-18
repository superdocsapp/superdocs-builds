"""Closing checklist parser supporting JSON, Markdown tables, CSV, and plain text."""

import csv
import json
import os
import re
from typing import Any, Dict, List, Optional

from core.enums import DocumentCategory, PriorityLevel
from core.models import ChecklistItem, ClosingChecklist


class ChecklistParser:
    """Parses closing checklists into standardized ClosingChecklist schemas."""

    def parse_file(self, file_path: str) -> ClosingChecklist:
        """Parses a closing checklist file from disk."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Checklist file not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower().replace(".", "")
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        if ext == "json":
            return self.parse_json(content)
        elif ext in ["md", "markdown"]:
            return self.parse_markdown(content)
        elif ext == "csv":
            return self.parse_csv(file_path)
        else:
            return self.parse_markdown(content)

    def parse_json(self, json_str: str) -> ClosingChecklist:
        """Parses a JSON checklist specification."""
        data = json.loads(json_str)
        items = []
        raw_items = data.get("items", [])
        for idx, it in enumerate(raw_items, start=1):
            tab_num = it.get("tab_number", idx)
            item = ChecklistItem(
                item_id=it.get("item_id", f"ITEM-{tab_num:03d}"),
                tab_number=tab_num,
                tab_label=it.get("tab_label", f"Tab {tab_num:02d}"),
                category=self._parse_category(it.get("category")),
                title=it.get("title", f"Document {tab_num}"),
                description=it.get("description"),
                required_parties=it.get("required_parties", []),
                signatures_required=it.get("signatures_required", True),
                priority=self._parse_priority(it.get("priority")),
                governing_law=it.get("governing_law"),
                responsible_counsel=it.get("responsible_counsel", "Buyer's Counsel"),
                notes=it.get("notes"),
            )
            items.append(item)

        return ClosingChecklist(
            deal_name=data.get("deal_name", "M&A Transaction Closing"),
            buyer_entity=data.get("buyer_entity", "Acquirer LLC"),
            target_entity=data.get("target_entity", "Target Corporation"),
            closing_date=data.get("closing_date", "Closing Date"),
            counsel_firm=data.get("counsel_firm", "Deal Counsel LLP"),
            total_items=len(items),
            items=items,
        )

    def parse_markdown(self, markdown_text: str) -> ClosingChecklist:
        """Parses markdown tables or lists into ClosingChecklist."""
        deal_name = "M&A Transaction Closing Binder"
        buyer_entity = "Buyer Entity"
        target_entity = "Target Entity"
        closing_date = "Closing Date"
        counsel_firm = "Transaction Counsel LLP"

        for line in markdown_text.splitlines():
            if line.startswith("# Deal:"):
                deal_name = line.replace("# Deal:", "").strip()
            elif line.startswith("# "):
                deal_name = line.replace("# ", "").strip()
            elif "Buyer:" in line:
                buyer_entity = line.split("Buyer:")[1].strip()
            elif "Target:" in line:
                target_entity = line.split("Target:")[1].strip()
            elif "Date:" in line:
                closing_date = line.split("Date:")[1].strip()

        items: List[ChecklistItem] = []
        current_category = DocumentCategory.PRIMARY_AGREEMENT
        tab_counter = 1

        table_row_regex = re.compile(r"^\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]*)\s*\|\s*([^|]*)\s*\|\s*([^|]*)\s*\|$")
        bullet_regex = re.compile(r"^(?:[\*\-]\s+|\d+\.\s+)(?:(?:Tab\s+(\d+)|\[Tab\s+(\d+)\])[:\s]+)?(.+)$", re.IGNORECASE)

        for line in markdown_text.splitlines():
            trimmed = line.strip()
            if not trimmed:
                continue

            # Skip table delimiter rows like | :--- | :--- | or |---|---|
            if re.match(r"^\|\s*[-:\s|]+\s*\|?$", trimmed):
                continue

            if trimmed.startswith("## ") or trimmed.startswith("### "):
                header_text = trimmed.lstrip("#").strip()
                current_category = self._parse_category(header_text)
                continue

            if match := table_row_regex.match(trimmed):
                col1, col2, col3, col4, col5 = [c.strip() for c in match.groups()]
                if "Tab" in col1 and "Title" in col2:
                    continue
                if ":---" in col1 or ":---" in col2 or "---" in col2:
                    continue

                tab_match = re.search(r"\d+", col1)
                tab_num = int(tab_match.group(0)) if tab_match else tab_counter
                tab_counter = max(tab_counter, tab_num + 1)

                parties = [p.strip() for p in col3.split(",") if p.strip()] if col3 else []
                sig_req = not (col4.lower() in ["no", "false", "none", "n/a", "seal", "filing"])
                cat = self._parse_category(col5) if col5 else current_category

                items.append(
                    ChecklistItem(
                        item_id=f"ITEM-{tab_num:03d}",
                        tab_number=tab_num,
                        tab_label=f"Tab {tab_num:02d}",
                        category=cat,
                        title=col2,
                        required_parties=parties,
                        signatures_required=sig_req,
                        priority=PriorityLevel.MANDATORY_CLOSING_CONDITION,
                    )
                )

            elif bullet_match := bullet_regex.match(trimmed):
                tab_g1, tab_g2, title_text = bullet_match.groups()
                tab_num_str = tab_g1 or tab_g2
                tab_num = int(tab_num_str) if tab_num_str else tab_counter
                tab_counter = max(tab_counter, tab_num + 1)

                items.append(
                    ChecklistItem(
                        item_id=f"ITEM-{tab_num:03d}",
                        tab_number=tab_num,
                        tab_label=f"Tab {tab_num:02d}",
                        category=current_category,
                        title=title_text.strip(),
                        signatures_required=True,
                        priority=PriorityLevel.MANDATORY_CLOSING_CONDITION,
                    )
                )

        return ClosingChecklist(
            deal_name=deal_name,
            buyer_entity=buyer_entity,
            target_entity=target_entity,
            closing_date=closing_date,
            counsel_firm=counsel_firm,
            total_items=len(items),
            items=items,
        )

    def parse_csv(self, file_path: str) -> ClosingChecklist:
        """Parses a CSV checklist file."""
        items = []
        tab_counter = 1
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tab_num = int(row.get("Tab", tab_counter))
                tab_counter = max(tab_counter, tab_num + 1)
                title = row.get("Title", row.get("Document", f"Document {tab_num}"))
                parties_raw = row.get("Parties", "")
                parties = [p.strip() for p in parties_raw.split(";") if p.strip()]
                sig_req = row.get("SignaturesRequired", "true").lower() in ["true", "yes", "1"]

                item = ChecklistItem(
                    item_id=f"ITEM-{tab_num:03d}",
                    tab_number=tab_num,
                    tab_label=f"Tab {tab_num:02d}",
                    category=self._parse_category(row.get("Category")),
                    title=title,
                    description=row.get("Description"),
                    required_parties=parties,
                    signatures_required=sig_req,
                    responsible_counsel=row.get("ResponsibleCounsel", "Deal Counsel"),
                )
                items.append(item)

        return ClosingChecklist(
            deal_name="M&A Closing Checklist",
            buyer_entity="Buyer",
            target_entity="Target",
            closing_date="Closing Date",
            counsel_firm="Deal Counsel LLP",
            total_items=len(items),
            items=items,
        )

    def _parse_category(self, cat_str: Optional[str]) -> DocumentCategory:
        if not cat_str:
            return DocumentCategory.PRIMARY_AGREEMENT
        s = cat_str.upper()
        if "PRIMARY" in s or "MERGER" in s or "PURCHASE" in s:
            return DocumentCategory.PRIMARY_AGREEMENT
        elif "ANCILLARY" in s or "ESCROW" in s or "TRANSITION" in s or "COMMERCIAL" in s:
            return DocumentCategory.ANCILLARY_AGREEMENT
        elif "CORPORATE" in s or "GOVERNANCE" in s or "RESOLUTION" in s or "BYLAW" in s or "CHARTER" in s:
            return DocumentCategory.CORPORATE_GOVERNANCE
        elif "REGULATORY" in s or "CONSENT" in s or "FILING" in s or "ANTITRUST" in s or "HSR" in s:
            return DocumentCategory.REGULATORY_CONSENT
        elif "OFFICER" in s or "CERTIFICATE" in s or "OPINION" in s:
            return DocumentCategory.OFFICER_CERTIFICATE
        elif "FINANCIAL" in s or "FUNDS FLOW" in s or "PAYOFF" in s or "WIRE" in s:
            return DocumentCategory.FINANCIAL_CLOSING
        elif "DISCLOSURE" in s or "SCHEDULE" in s or "EXHIBIT" in s:
            return DocumentCategory.DISCLOSURE_SCHEDULE
        elif "POST" in s:
            return DocumentCategory.POST_CLOSING
        return DocumentCategory.PRIMARY_AGREEMENT

    def _parse_priority(self, p_str: Optional[str]) -> PriorityLevel:
        if not p_str:
            return PriorityLevel.MANDATORY_CLOSING_CONDITION
        s = p_str.upper()
        if "POST" in s:
            return PriorityLevel.POST_CLOSING_OBLIGATION
        elif "OPTIONAL" in s:
            return PriorityLevel.OPTIONAL_CONVENIENCE
        elif "REQUIRED" in s:
            return PriorityLevel.REQUIRED_DELIVERABLE
        return PriorityLevel.MANDATORY_CLOSING_CONDITION
