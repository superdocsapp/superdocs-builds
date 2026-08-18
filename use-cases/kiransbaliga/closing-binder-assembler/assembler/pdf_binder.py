"""Navigable M&A PDF Closing-Binder Assembler with hyperlinked TOC, dividers, and bookmarks."""

import io
import os
import tempfile
from typing import Dict, List, Optional, Tuple

import pypdf
from pypdf.annotations import Link
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from assembler.styles import (
    BG_LIGHT,
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
from core.enums import ExecutionStatus
from core.models import BinderSpec, ChecklistItem, ClosingChecklist, DocumentMetadata, MatchResult, TabEntry


class PDFBinderAssembler:
    """Assembles single navigable M&A PDF Closing Binder with live hyperlinked TOC, dividers, and running headers."""

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = output_dir or tempfile.gettempdir()
        self.styles = get_legal_binder_styles()

    def assemble_binder(
        self,
        checklist: ClosingChecklist,
        matches: List[MatchResult],
        documents_map: Dict[str, DocumentMetadata],
        output_pdf_path: str,
        deal_title: Optional[str] = None,
    ) -> str:
        """Assembles full navigable PDF closing binder."""
        os.makedirs(os.path.dirname(os.path.abspath(output_pdf_path)), exist_ok=True)
        deal_name = deal_title or checklist.deal_name

        tab_entries: List[TabEntry] = []
        doc_pdf_bytes_list: List[Tuple[TabEntry, bytes]] = []

        for match in matches:
            item = next((it for it in checklist.items if it.item_id == match.checklist_item_id), None)
            if not item:
                continue

            doc_meta = documents_map.get(match.doc_id) if match.doc_id else None
            doc_bytes, page_count = self._get_or_create_doc_pdf_bytes(item, doc_meta, match)
            
            tab_entry = TabEntry(
                tab_number=item.tab_number,
                tab_label=item.tab_label,
                category=item.category.value,
                title=item.title,
                document_path=doc_meta.file_path if doc_meta else None,
                page_count=page_count,
                execution_status=match.execution_status,
                signatories_summary=", ".join(item.required_parties) if item.required_parties else None,
            )
            tab_entries.append(tab_entry)
            doc_pdf_bytes_list.append((tab_entry, doc_bytes))

        estimated_toc_pages = max(1, (len(tab_entries) + 14) // 15)
        cover_and_toc_pages = 1 + estimated_toc_pages

        current_page_counter = cover_and_toc_pages + 1
        for tab in tab_entries:
            tab.start_page = current_page_counter
            current_page_counter += (1 + tab.page_count)

        cover_toc_pdf_bytes = self._render_cover_and_toc_pdf(checklist, tab_entries, deal_name)
        cover_toc_reader = pypdf.PdfReader(io.BytesIO(cover_toc_pdf_bytes))
        actual_cover_toc_pages = len(cover_toc_reader.pages)

        if actual_cover_toc_pages != cover_and_toc_pages:
            current_page_counter = actual_cover_toc_pages + 1
            for tab in tab_entries:
                tab.start_page = current_page_counter
                current_page_counter += (1 + tab.page_count)
            cover_toc_pdf_bytes = self._render_cover_and_toc_pdf(checklist, tab_entries, deal_name)
            cover_toc_reader = pypdf.PdfReader(io.BytesIO(cover_toc_pdf_bytes))

        raw_writer = pypdf.PdfWriter()

        for page in cover_toc_reader.pages:
            raw_writer.add_page(page)

        tab_start_indices: List[Tuple[TabEntry, int]] = []

        for tab, doc_bytes in doc_pdf_bytes_list:
            tab_start_page_idx = len(raw_writer.pages)
            tab_start_indices.append((tab, tab_start_page_idx))

            divider_pdf_bytes = self._render_tab_divider_pdf(checklist, tab, deal_name)
            divider_reader = pypdf.PdfReader(io.BytesIO(divider_pdf_bytes))
            for page in divider_reader.pages:
                raw_writer.add_page(page)

            if doc_bytes:
                doc_reader = pypdf.PdfReader(io.BytesIO(doc_bytes))
                for page in doc_reader.pages:
                    raw_writer.add_page(page)

        self._add_toc_hyperlink_annotations(raw_writer, tab_entries, actual_cover_toc_pages)
        
        # Apply Running Headers and build Outline Bookmarks on final writer
        final_pdf_bytes = self._apply_running_headers_and_outlines(
            raw_writer, deal_name, tab_entries, tab_start_indices
        )

        with open(output_pdf_path, "wb") as f:
            f.write(final_pdf_bytes)

        return os.path.abspath(output_pdf_path)

    def _render_cover_and_toc_pdf(
        self,
        checklist: ClosingChecklist,
        tabs: List[TabEntry],
        deal_name: str,
    ) -> bytes:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
        )

        story = []

        story.append(Spacer(1, 1.2 * inch))
        story.append(Paragraph(f"<b>{checklist.counsel_firm.upper()}</b>", self.styles["cover_firm"]))
        story.append(Spacer(1, 0.4 * inch))
        story.append(HRFlowable(width="60%", thickness=2, color=GOLD_ACCENT, spaceAfter=25, spaceBefore=10))
        story.append(Paragraph(deal_name.upper(), self.styles["cover_title"]))
        story.append(Paragraph("CLOSING BINDER & COMPILATION OF EXECUTED TRANSACTION DOCUMENTS", self.styles["cover_subtitle"]))
        story.append(HRFlowable(width="60%", thickness=1, color=BORDER_GREY, spaceAfter=30, spaceBefore=10))

        story.append(Spacer(1, 0.5 * inch))
        meta_table_data = [
            [Paragraph("<b>Acquiring Entity:</b>", self.styles["body_legal"]), Paragraph(checklist.buyer_entity, self.styles["body_legal"])],
            [Paragraph("<b>Target Entity:</b>", self.styles["body_legal"]), Paragraph(checklist.target_entity, self.styles["body_legal"])],
            [Paragraph("<b>Closing Date:</b>", self.styles["body_legal"]), Paragraph(checklist.closing_date, self.styles["body_legal"])],
            [Paragraph("<b>Total Transaction Tabs:</b>", self.styles["body_legal"]), Paragraph(f"{len(tabs)} Tabs", self.styles["body_legal"])],
            [Paragraph("<b>Compilation Firm:</b>", self.styles["body_legal"]), Paragraph(checklist.counsel_firm, self.styles["body_legal"])],
        ]
        meta_table = Table(meta_table_data, colWidths=[2.2 * inch, 4.0 * inch])
        meta_table.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, BORDER_GREY),
            ])
        )
        story.append(meta_table)

        story.append(Spacer(1, 0.8 * inch))
        story.append(
            Paragraph(
                "<font size=8 color='#64748B'>CONFIDENTIAL TRANSACTION RECORD - FOR PARTIES AND COUNSEL ONLY</font>",
                self.styles["cover_meta"],
            )
        )
        story.append(PageBreak())

        story.append(Paragraph("TABLE OF CONTENTS / INDEX OF TABS", self.styles["toc_heading"]))
        story.append(
            Paragraph(
                "<font color='#64748B'>Click any tab title to navigate directly to that document inside the binder.</font>",
                self.styles["toc_item"],
            )
        )
        story.append(HRFlowable(width="100%", thickness=1.5, color=NAVY_PRIMARY, spaceAfter=15, spaceBefore=8))

        current_cat = None
        for tab in tabs:
            if tab.category != current_cat:
                current_cat = tab.category
                story.append(Spacer(1, 8))
                story.append(Paragraph(f"<b>{current_cat.upper()}</b>", self.styles["toc_category"]))
                story.append(HRFlowable(width="100%", thickness=0.5, color=GOLD_ACCENT, spaceAfter=6, spaceBefore=2))

            status_color = SUCCESS_GREEN.hexval()
            status_text = "EXECUTED"
            if tab.execution_status == ExecutionStatus.UNSIGNED_DRAFT:
                status_color = DANGER_RED.hexval()
                status_text = "UNSIGNED DRAFT"
            elif tab.execution_status == ExecutionStatus.PARTIALLY_EXECUTED:
                status_color = WARNING_AMBER.hexval()
                status_text = "PARTIALLY SIGNED"
            elif tab.execution_status == ExecutionStatus.NON_SIGNATURE_DOC:
                status_color = SLATE_SECONDARY.hexval()
                status_text = "CERTIFIED FILING"
            elif tab.execution_status == ExecutionStatus.MISSING:
                status_color = DANGER_RED.hexval()
                status_text = "MISSING"

            row_data = [
                [
                    Paragraph(f"<b>{tab.tab_label}</b>", self.styles["toc_item"]),
                    Paragraph(f"{tab.title}", self.styles["toc_item"]),
                    Paragraph(f"<font color='{status_color}'><b>[{status_text}]</b></font>", self.styles["toc_item"]),
                    Paragraph(f"<b>Page {tab.start_page}</b>", self.styles["toc_item"]),
                ]
            ]
            row_table = Table(row_data, colWidths=[0.9 * inch, 3.8 * inch, 1.4 * inch, 0.9 * inch])
            row_table.setStyle(
                TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (3, 0), (3, 0), "RIGHT"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#F1F5F9")),
                ])
            )
            story.append(row_table)

        doc.build(story)
        return buffer.getvalue()

    def _render_tab_divider_pdf(
        self,
        checklist: ClosingChecklist,
        tab: TabEntry,
        deal_name: str,
    ) -> bytes:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=1.0 * inch,
            rightMargin=1.0 * inch,
            topMargin=1.5 * inch,
            bottomMargin=1.5 * inch,
        )

        story = []
        story.append(Spacer(1, 1.0 * inch))
        story.append(Paragraph(f"<b>{tab.category.upper()}</b>", self.styles["tab_category_badge"]))
        story.append(Paragraph(tab.tab_label.upper(), self.styles["tab_number_large"]))
        story.append(HRFlowable(width="40%", thickness=2, color=GOLD_ACCENT, spaceAfter=20, spaceBefore=10))
        story.append(Paragraph(f"<b>{tab.title}</b>", self.styles["tab_title"]))
        story.append(HRFlowable(width="40%", thickness=1, color=BORDER_GREY, spaceAfter=25, spaceBefore=15))

        status_desc = "Fully Executed by All Required Parties"
        status_color = SUCCESS_GREEN.hexval()
        if tab.execution_status == ExecutionStatus.UNSIGNED_DRAFT:
            status_desc = "Unsigned Draft / Execution Copy Pending"
            status_color = DANGER_RED.hexval()
        elif tab.execution_status == ExecutionStatus.PARTIALLY_EXECUTED:
            status_desc = "Partially Executed / Missing Counterparty Signature"
            status_color = WARNING_AMBER.hexval()
        elif tab.execution_status == ExecutionStatus.NON_SIGNATURE_DOC:
            status_desc = "Certified Corporate Filing / Secretary of State Certificate"
            status_color = SLATE_SECONDARY.hexval()
        elif tab.execution_status == ExecutionStatus.MISSING:
            status_desc = "Missing Deliverable at Time of Closing"
            status_color = DANGER_RED.hexval()

        meta_rows = [
            [Paragraph("<b>Status:</b>", self.styles["body_legal"]), Paragraph(f"<font color='{status_color}'><b>{status_desc}</b></font>", self.styles["body_legal"])],
            [Paragraph("<b>Signatories:</b>", self.styles["body_legal"]), Paragraph(tab.signatories_summary or "See execution blocks", self.styles["body_legal"])],
            [Paragraph("<b>Binder Location:</b>", self.styles["body_legal"]), Paragraph(f"Starts on Page {tab.start_page} ({tab.page_count} page{'s' if tab.page_count != 1 else ''})", self.styles["body_legal"])],
        ]
        tab_meta_table = Table(meta_rows, colWidths=[1.8 * inch, 4.2 * inch])
        tab_meta_table.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, BORDER_GREY),
            ])
        )
        story.append(tab_meta_table)

        doc.build(story)
        return buffer.getvalue()

    def _get_or_create_doc_pdf_bytes(
        self,
        item: ChecklistItem,
        doc_meta: Optional[DocumentMetadata],
        match: MatchResult,
    ) -> Tuple[bytes, int]:
        if doc_meta and doc_meta.file_path and os.path.exists(doc_meta.file_path):
            if doc_meta.file_type == "pdf":
                with open(doc_meta.file_path, "rb") as f:
                    content = f.read()
                reader = pypdf.PdfReader(io.BytesIO(content))
                return content, len(reader.pages)
            else:
                return self._render_text_as_pdf(doc_meta.detected_title or item.title, doc_meta.raw_text)

        return self._render_missing_item_pdf(item, match)

    def _render_text_as_pdf(self, title: str, text: str) -> Tuple[bytes, int]:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
        )

        story = [
            Paragraph(f"<b>{title}</b>", self.styles["toc_heading"]),
            HRFlowable(width="100%", thickness=1, color=BORDER_GREY, spaceAfter=15, spaceBefore=5),
        ]

        for para in text.split("\n\n"):
            clean_para = para.strip().replace("\n", " ")
            if clean_para:
                story.append(Paragraph(clean_para, self.styles["body_legal"]))
                story.append(Spacer(1, 8))

        doc.build(story)
        rendered_bytes = buffer.getvalue()
        reader = pypdf.PdfReader(io.BytesIO(rendered_bytes))
        return rendered_bytes, len(reader.pages)

    def _render_missing_item_pdf(self, item: ChecklistItem, match: MatchResult) -> Tuple[bytes, int]:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=1.0 * inch,
            rightMargin=1.0 * inch,
            topMargin=2.0 * inch,
            bottomMargin=1.5 * inch,
        )

        story = [
            Paragraph("<b>NOTICE: DOCUMENT MISSING FROM CLOSING BINDER</b>", self.styles["tab_title"]),
            HRFlowable(width="60%", thickness=2, color=DANGER_RED, spaceAfter=20, spaceBefore=10),
            Paragraph(
                f"<b>Checklist Item:</b> {item.tab_label} - {item.title}<br/>"
                f"<b>Responsible Counsel:</b> {item.responsible_counsel or 'Counsel'}<br/>"
                f"<b>Category:</b> {item.category.value}<br/>"
                f"<b>Closing Status:</b> <font color='red'><b>ITEM NOT DELIVERED AT CLOSING</b></font>",
                self.styles["body_legal"],
            ),
            Spacer(1, 20),
            Paragraph(
                "<i>This tab divider reserves the index position for post-closing execution and filing delivery.</i>",
                self.styles["cover_meta"],
            ),
        ]

        doc.build(story)
        b = buffer.getvalue()
        return b, 1

    def _add_toc_hyperlink_annotations(
        self,
        writer: pypdf.PdfWriter,
        tabs: List[TabEntry],
        toc_page_count: int,
    ):
        for tab in tabs:
            target_page_idx = min(len(writer.pages) - 1, max(0, tab.start_page - 1))

            for page_idx in range(1, toc_page_count):
                if page_idx < len(writer.pages):
                    link_annot = Link(
                        rect=(54, 100, 558, 700),
                        target_page_index=target_page_idx,
                    )
                    writer.add_annotation(
                        page_number=page_idx,
                        annotation=link_annot,
                    )
                    break

    def _apply_running_headers_and_outlines(
        self,
        raw_writer: pypdf.PdfWriter,
        deal_name: str,
        tabs: List[TabEntry],
        tab_start_indices: List[Tuple[TabEntry, int]],
    ) -> bytes:
        total_pages = len(raw_writer.pages)
        temp_buffer = io.BytesIO()
        raw_writer.write(temp_buffer)
        temp_buffer.seek(0)

        reader = pypdf.PdfReader(temp_buffer)
        output_writer = pypdf.PdfWriter()

        page_to_tab: Dict[int, TabEntry] = {}
        for tab in tabs:
            end_page = tab.start_page + tab.page_count
            for p in range(tab.start_page, end_page + 1):
                page_to_tab[p] = tab

        for page_idx in range(total_pages):
            page_num = page_idx + 1
            page = reader.pages[page_idx]

            if page_num == 1:
                output_writer.add_page(page)
                continue

            stamp_buffer = io.BytesIO()
            can = canvas.Canvas(stamp_buffer, pagesize=letter)
            
            can.setFont("Helvetica", 8)
            can.setFillColor(colors.HexColor("#64748B"))
            
            tab_for_page = page_to_tab.get(page_num)
            if tab_for_page:
                tab_snippet = f"{tab_for_page.tab_label}: {tab_for_page.title}"
                if len(tab_snippet) > 45:
                    tab_snippet = tab_snippet[:42] + "..."
                header_text = f"{deal_name}  |  {tab_snippet}"
            else:
                header_text = f"{deal_name}  |  Table of Contents"

            can.drawString(54, 750, header_text)
            can.setStrokeColor(BORDER_GREY)
            can.setLineWidth(0.5)
            can.line(54, 742, 558, 742)

            can.drawString(54, 40, "CONFIDENTIAL & PRIVILEGED - M&A TRANSACTION RECORD")
            page_str = f"Page {page_num} of {total_pages}"
            can.drawRightString(558, 40, page_str)
            can.line(54, 52, 558, 52)

            can.save()
            stamp_buffer.seek(0)
            stamp_reader = pypdf.PdfReader(stamp_buffer)
            page.merge_page(stamp_reader.pages[0])
            output_writer.add_page(page)

        # Build Bookmarks / Outline Hierarchy on output_writer
        category_outlines: Dict[str, pypdf.generic.IndirectObject] = {}
        for tab, start_idx in tab_start_indices:
            cat_name = tab.category
            if cat_name not in category_outlines:
                parent = output_writer.add_outline_item(
                    title=cat_name,
                    page_number=start_idx,
                )
                category_outlines[cat_name] = parent

            parent = category_outlines[cat_name]
            output_writer.add_outline_item(
                title=f"{tab.tab_label}: {tab.title} [{tab.execution_status.value}]",
                page_number=start_idx,
                parent=parent,
            )

        final_out = io.BytesIO()
        output_writer.write(final_out)
        return final_out.getvalue()
