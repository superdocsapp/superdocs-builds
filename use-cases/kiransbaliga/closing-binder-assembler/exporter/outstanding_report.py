"""Client-ready Outstanding Items Report generator in PDF, Markdown, and DOCX formats."""

from datetime import datetime, timezone
import io
import os
from typing import Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from assembler.styles import (
    BORDER_GREY,
    DANGER_RED,
    GOLD_ACCENT,
    NAVY_PRIMARY,
    SLATE_SECONDARY,
    SUCCESS_GREEN,
    TEXT_DARK,
    TEXT_MUTED,
    WARNING_AMBER,
    get_legal_binder_styles,
)
from core.enums import ExecutionStatus, PriorityLevel
from core.models import (
    ClosingChecklist,
    DocumentMetadata,
    MatchResult,
    OutstandingItemEntry,
    OutstandingReport,
)


class OutstandingReportGenerator:
    """Generates an executive, client-ready Outstanding Items Document."""

    def __init__(self):
        self.styles = get_legal_binder_styles()

    def generate_report(
        self,
        checklist: ClosingChecklist,
        matches: List[MatchResult],
        documents_map: Dict[str, DocumentMetadata],
        output_base_path: str,
    ) -> Dict[str, str]:
        """Generates client-ready Outstanding Items Report in PDF and Markdown."""
        report_data = self._compile_report_data(checklist, matches, documents_map)

        md_path = f"{output_base_path}.md"
        self._write_markdown_report(md_path, report_data, checklist)

        pdf_path = f"{output_base_path}.pdf"
        self._write_pdf_report(pdf_path, report_data, checklist)

        return {
            "pdf_path": os.path.abspath(pdf_path),
            "md_path": os.path.abspath(md_path),
            "readiness_percentage": report_data.closing_readiness_percentage,
            "is_closing_ready": report_data.is_closing_ready,
        }

    def _compile_report_data(
        self,
        checklist: ClosingChecklist,
        matches: List[MatchResult],
        documents_map: Dict[str, DocumentMetadata],
    ) -> OutstandingReport:
        missing_items: List[OutstandingItemEntry] = []
        incomplete_items: List[OutstandingItemEntry] = []
        satisfied_items: List[OutstandingItemEntry] = []

        for match in matches:
            item = next((it for it in checklist.items if it.item_id == match.checklist_item_id), None)
            if not item:
                continue

            doc_meta = documents_map.get(match.doc_id) if match.doc_id else None

            if match.execution_status == ExecutionStatus.MISSING:
                missing_items.append(
                    OutstandingItemEntry(
                        tab_number=item.tab_number,
                        tab_label=item.tab_label,
                        title=item.title,
                        category=item.category.value,
                        status=ExecutionStatus.MISSING,
                        responsible_counsel=item.responsible_counsel or "Buyer / Seller Counsel",
                        missing_signatories=item.required_parties,
                        action_required="Deliver fully executed original or PDF copy for closing file.",
                        priority=item.priority,
                    )
                )
            elif match.execution_status in [ExecutionStatus.UNSIGNED_DRAFT, ExecutionStatus.PARTIALLY_EXECUTED]:
                missing_signers = []
                if doc_meta:
                    missing_signers = [b.party_name for b in doc_meta.signature_blocks if not b.is_signed]
                if not missing_signers:
                    missing_signers = item.required_parties

                incomplete_items.append(
                    OutstandingItemEntry(
                        tab_number=item.tab_number,
                        tab_label=item.tab_label,
                        title=item.title,
                        category=item.category.value,
                        status=match.execution_status,
                        responsible_counsel=item.responsible_counsel or "Counsel",
                        missing_signatories=missing_signers,
                        action_required=f"Obtain executed counterpart signature pages from: {', '.join(missing_signers)}.",
                        priority=item.priority,
                    )
                )
            else:
                satisfied_items.append(
                    OutstandingItemEntry(
                        tab_number=item.tab_number,
                        tab_label=item.tab_label,
                        title=item.title,
                        category=item.category.value,
                        status=match.execution_status,
                        responsible_counsel=item.responsible_counsel or "Counsel",
                        action_required="None - Item is fully satisfied.",
                        priority=item.priority,
                    )
                )

        total_count = len(checklist.items)
        satisfied_count = len(satisfied_items)
        missing_count = len(missing_items)
        incomplete_count = len(incomplete_items)
        readiness = round((satisfied_count / total_count * 100) if total_count > 0 else 0.0, 1)

        return OutstandingReport(
            deal_name=checklist.deal_name,
            generated_at=datetime.now(timezone.utc).strftime("%B %d, %Y - %H:%M UTC"),
            total_checklist_items=total_count,
            satisfied_count=satisfied_count,
            missing_count=missing_count,
            unsigned_count=sum(1 for it in incomplete_items if it.status == ExecutionStatus.UNSIGNED_DRAFT),
            partially_executed_count=sum(1 for it in incomplete_items if it.status == ExecutionStatus.PARTIALLY_EXECUTED),
            closing_readiness_percentage=readiness,
            is_closing_ready=(missing_count == 0 and incomplete_count == 0),
            missing_items=missing_items,
            incomplete_items=incomplete_items,
            satisfied_items=satisfied_items,
        )

    def _write_pdf_report(self, output_path: str, report: OutstandingReport, checklist: ClosingChecklist):
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
        )

        story = []

        story.append(Paragraph(f"<b>{checklist.counsel_firm.upper()}</b>", self.styles["cover_firm"]))
        story.append(Paragraph(f"TRANSACTION OUTSTANDING ITEMS MEMORANDUM", self.styles["cover_title"]))
        story.append(Paragraph(f"<b>Deal:</b> {report.deal_name}", self.styles["cover_subtitle"]))
        story.append(HRFlowable(width="100%", thickness=1.5, color=NAVY_PRIMARY, spaceAfter=15, spaceBefore=5))

        gauge_color = SUCCESS_GREEN.hexval() if report.is_closing_ready else WARNING_AMBER.hexval()
        summary_text = (
            f"<b>Closing Readiness:</b> <font color='{gauge_color}'><b>{report.closing_readiness_percentage}% COMPLETED</b></font><br/>"
            f"<b>Total Checklist Items:</b> {report.total_checklist_items} &nbsp;|&nbsp; "
            f"<b>Satisfied:</b> {report.satisfied_count} &nbsp;|&nbsp; "
            f"<b>Missing:</b> {report.missing_count} &nbsp;|&nbsp; "
            f"<b>Pending Signatures:</b> {report.unsigned_count + report.partially_executed_count}<br/>"
            f"<b>Generated:</b> {report.generated_at}"
        )
        summary_table = Table([[Paragraph(summary_text, self.styles["body_legal"])]], colWidths=[7.0 * inch])
        summary_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 1, BORDER_GREY),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ])
        )
        story.append(summary_table)
        story.append(Spacer(1, 15))

        if report.missing_items:
            story.append(Paragraph("<b>1. MISSING DELIVERABLES (CLOSING BLOCKERS)</b>", self.styles["toc_category"]))
            story.append(HRFlowable(width="100%", thickness=0.5, color=DANGER_RED, spaceAfter=8, spaceBefore=2))

            table_rows = [
                [
                    Paragraph("<b>Tab</b>", self.styles["body_legal"]),
                    Paragraph("<b>Document Title</b>", self.styles["body_legal"]),
                    Paragraph("<b>Responsible</b>", self.styles["body_legal"]),
                    Paragraph("<b>Required Action</b>", self.styles["body_legal"]),
                ]
            ]
            for it in report.missing_items:
                table_rows.append([
                    Paragraph(f"<b>{it.tab_label}</b>", self.styles["body_legal"]),
                    Paragraph(it.title, self.styles["body_legal"]),
                    Paragraph(it.responsible_counsel, self.styles["body_legal"]),
                    Paragraph(f"<font color='{DANGER_RED.hexval()}'>{it.action_required}</font>", self.styles["body_legal"]),
                ])

            t = Table(table_rows, colWidths=[0.8 * inch, 2.5 * inch, 1.4 * inch, 2.3 * inch])
            t.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GREY),
                ])
            )
            story.append(t)
            story.append(Spacer(1, 15))

        if report.incomplete_items:
            story.append(Paragraph("<b>2. INCOMPLETE & UNSIGNED DOCUMENTS</b>", self.styles["toc_category"]))
            story.append(HRFlowable(width="100%", thickness=0.5, color=WARNING_AMBER, spaceAfter=8, spaceBefore=2))

            table_rows = [
                [
                    Paragraph("<b>Tab</b>", self.styles["body_legal"]),
                    Paragraph("<b>Document Title</b>", self.styles["body_legal"]),
                    Paragraph("<b>Missing Signatories</b>", self.styles["body_legal"]),
                    Paragraph("<b>Deficiency</b>", self.styles["body_legal"]),
                ]
            ]
            for it in report.incomplete_items:
                signers = ", ".join(it.missing_signatories) if it.missing_signatories else "All Parties"
                table_rows.append([
                    Paragraph(f"<b>{it.tab_label}</b>", self.styles["body_legal"]),
                    Paragraph(it.title, self.styles["body_legal"]),
                    Paragraph(f"<b>{signers}</b>", self.styles["body_legal"]),
                    Paragraph(f"<font color='{WARNING_AMBER.hexval()}'>{it.action_required}</font>", self.styles["body_legal"]),
                ])

            t = Table(table_rows, colWidths=[0.8 * inch, 2.5 * inch, 1.7 * inch, 2.0 * inch])
            t.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GREY),
                ])
            )
            story.append(t)
            story.append(Spacer(1, 15))

        story.append(Paragraph("<b>3. SATISFIED TRANSACTION ITEMS SUMMARY</b>", self.styles["toc_category"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=SUCCESS_GREEN, spaceAfter=8, spaceBefore=2))
        story.append(
            Paragraph(
                f"A total of <b>{report.satisfied_count} items</b> are fully executed and satisfied for closing. "
                f"Full counterpart execution packets are indexed and compiled into the primary closing binder.",
                self.styles["body_legal"],
            )
        )

        doc.build(story)

    def _write_markdown_report(self, output_path: str, report: OutstandingReport, checklist: ClosingChecklist):
        lines = [
            f"# {checklist.counsel_firm}",
            f"## TRANSACTION OUTSTANDING ITEMS MEMORANDUM",
            f"",
            f"**Deal:** {report.deal_name}  ",
            f"**Buyer:** {checklist.buyer_entity}  ",
            f"**Target:** {checklist.target_entity}  ",
            f"**Closing Date:** {checklist.closing_date}  ",
            f"**Generated:** {report.generated_at}  ",
            f"**Closing Readiness Score:** `{report.closing_readiness_percentage}%` ({report.satisfied_count}/{report.total_checklist_items} Items Satisfied)",
            f"",
            f"---",
            f"",
            f"### 1. Critical Closing Blockers (Missing Deliverables)",
            f"",
        ]

        if report.missing_items:
            lines.extend([
                f"| Tab | Document Title | Category | Responsible Counsel | Required Action |",
                f"| :--- | :--- | :--- | :--- | :--- |",
            ])
            for it in report.missing_items:
                lines.append(f"| **{it.tab_label}** | {it.title} | {it.category} | {it.responsible_counsel} | ❌ {it.action_required} |")
        else:
            lines.append("✅ **No missing documents. All checklist deliverables received.**")

        lines.extend([
            f"",
            f"### 2. Incomplete & Unsigned Documents",
            f"",
        ])

        if report.incomplete_items:
            lines.extend([
                f"| Tab | Document Title | Status | Missing Signatories | Required Action |",
                f"| :--- | :--- | :--- | :--- | :--- |",
            ])
            for it in report.incomplete_items:
                signers = ", ".join(it.missing_signatories) if it.missing_signatories else "All Parties"
                lines.append(f"| **{it.tab_label}** | {it.title} | `{it.status.value}` | {signers} | ⚠️ {it.action_required} |")
        else:
            lines.append("✅ **All delivered documents are fully executed with no missing signatures.**")

        lines.extend([
            f"",
            f"### 3. Satisfied Items Index ({report.satisfied_count} Documents)",
            f"",
            f"| Tab | Document Title | Status |",
            f"| :--- | :--- | :--- |",
        ])
        for it in report.satisfied_items:
            lines.append(f"| {it.tab_label} | {it.title} | ✅ `{it.status.value}` |")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
