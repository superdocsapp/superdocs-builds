from io import BytesIO
from typing import List, Dict, Any, Optional
from xml.sax.saxutils import escape
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Image as RLImage, Table, TableStyle, KeepTogether

from backend.logging_config import get_logger
from backend.core.export.screenplay_layout import (
    DEFAULT_SCREENPLAY_LAYOUT,
    calculate_element_spacing,
)

logger = get_logger(__name__)


class NumberedMemoCanvas(canvas.Canvas):
    """
    Two-pass canvas for professional reports/memos that draws running footer with Page X of Y.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_memo_footer(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_memo_footer(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica", 8.5)
        self.setFillColor(colors.HexColor("#6B7280"))

        # Footer divider line
        self.setStrokeColor(colors.HexColor("#E5E7EB"))
        self.setLineWidth(0.5)
        self.line(0.75 * inch, 0.55 * inch, (8.5 - 0.75) * inch, 0.55 * inch)

        # Left: Memo Title
        self.drawString(0.75 * inch, 0.38 * inch, "Tariff Classification Memo")

        # Right: Page X of Y
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString((8.5 - 0.75) * inch, 0.38 * inch, page_text)
        self.restoreState()


def _sanitize_xml(text: str) -> str:
    """Escape special characters for ReportLab XML/HTML-like formatting."""
    if not text:
        return ""
    return escape(text)



class PDFGenerator:
    """
    Generate PDF documents from structured data.

    Supports:
      1. Standard Screenplay PDF generation (Courier 12pt, US Letter, industry standard margins & indents).
      2. Tariff Memo PDF generation (Canonical formatted memo with metadata, sections, citations, and images).
      3. Tariff Report PDF generation (Review summaries with claims).
    """

    def generate_screenplay_pdf(
        self,
        formatting_items: List[Dict[str, Any]],
        title: str = "Untitled Screenplay",
        workspace_name: str = "",
    ) -> bytes:
        """
        Generate a PDF with industry-standard screenplay formatting.

        Conforms to standard screenplay layout:
          - US Letter (8.5in x 11in)
          - Margins: Left 1.5in, Right 1.0in, Top 1.0in, Bottom 1.0in
          - Courier 12pt monospace font throughout
          - Elements: TITLE, AUTHOR/CREDIT, SCENE_HEADING, ACTION,
            CHARACTER, PARENTHETICAL, DIALOGUE, TRANSITION, SHOT, PAGE_NUMBER, END
          - No generic document header or workspace metadata
          - Review status: approved/pending uses formatted_text, rejected uses original_text
        """
        logger.info("generating_screenplay_pdf", item_count=len(formatting_items))

        buffer = BytesIO()
        cfg = DEFAULT_SCREENPLAY_LAYOUT
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=cfg.margin_left_in * inch,
            rightMargin=cfg.margin_right_in * inch,
            topMargin=cfg.margin_top_in * inch,
            bottomMargin=cfg.margin_bottom_in * inch,
        )

        story = []

        # Filter out empty items and page_number elements (page numbers live in header)
        valid_items = [
            item for item in sorted(formatting_items, key=lambda x: x.get("element_index", 0))
            if item.get("element_type") != "page_number" and (
                (item.get("original_text") if item.get("status") == "rejected" else item.get("formatted_text")) or ""
            ).strip()
        ]

        for idx, item in enumerate(valid_items):
            status = item.get("status", "pending")
            text = item.get("original_text", "") if status == "rejected" else item.get("formatted_text", "")
            element_type = item.get("element_type", "action")

            clean_text = text.strip()
            is_rejected = (status == "rejected")
            prev_item = valid_items[idx - 1] if idx > 0 else None
            next_item = valid_items[idx + 1] if idx + 1 < len(valid_items) else None
            prev_type = prev_item.get("element_type") if prev_item else None
            next_type = next_item.get("element_type") if next_item else None

            space_before, space_after = calculate_element_spacing(element_type, prev_type, next_type, cfg)

            if element_type == "title":
                style = ParagraphStyle(
                    f"ScreenplayTitle_{idx}",
                    fontName=cfg.font_name_pdf_bold,
                    fontSize=cfg.font_size_pt,
                    leading=cfg.leading_pt,
                    alignment=1,
                    spaceBefore=space_before,
                    spaceAfter=space_after,
                    textColor=colors.black,
                )
                story.append(Paragraph(_sanitize_xml(clean_text), style))

            elif element_type in ("author", "author_credit", "credit"):
                style = ParagraphStyle(
                    f"ScreenplayAuthor_{idx}",
                    fontName=cfg.font_name_pdf,
                    fontSize=cfg.font_size_pt,
                    leading=cfg.leading_pt,
                    alignment=1,
                    spaceBefore=space_before,
                    spaceAfter=space_after,
                    textColor=colors.black,
                )
                story.append(Paragraph(_sanitize_xml(clean_text), style))

            elif element_type == "scene_heading":
                style = ParagraphStyle(
                    f"ScreenplaySceneHeading_{idx}",
                    fontName=cfg.font_name_pdf_bold,
                    fontSize=cfg.font_size_pt,
                    leading=cfg.leading_pt,
                    alignment=0,
                    leftIndent=cfg.scene_heading_left_in * inch,
                    rightIndent=cfg.scene_heading_right_in * inch,
                    spaceBefore=space_before,
                    spaceAfter=space_after,
                    keepWithNext=True,
                    textColor=colors.black,
                )
                run_text = clean_text if is_rejected else clean_text.upper()
                story.append(Paragraph(_sanitize_xml(run_text), style))

            elif element_type == "character":
                style = ParagraphStyle(
                    f"ScreenplayCharacter_{idx}",
                    fontName=cfg.font_name_pdf_bold,
                    fontSize=cfg.font_size_pt,
                    leading=cfg.leading_pt,
                    alignment=0,
                    leftIndent=cfg.character_left_in * inch,
                    rightIndent=cfg.character_right_in * inch,
                    spaceBefore=space_before,
                    spaceAfter=space_after,
                    keepWithNext=True,
                    textColor=colors.black,
                )
                run_text = clean_text if is_rejected else clean_text.upper()
                story.append(Paragraph(_sanitize_xml(run_text), style))

            elif element_type == "parenthetical":
                style = ParagraphStyle(
                    f"ScreenplayParenthetical_{idx}",
                    fontName=cfg.font_name_pdf,
                    fontSize=cfg.font_size_pt,
                    leading=cfg.leading_pt,
                    alignment=0,
                    leftIndent=cfg.parenthetical_left_in * inch,
                    rightIndent=cfg.parenthetical_right_in * inch,
                    spaceBefore=space_before,
                    spaceAfter=space_after,
                    keepWithNext=True,
                    textColor=colors.black,
                )
                if is_rejected:
                    paren_text = clean_text
                else:
                    paren_text = clean_text
                    if not paren_text.startswith("("):
                        paren_text = "(" + paren_text
                    if not paren_text.endswith(")"):
                        paren_text = paren_text + ")"
                story.append(Paragraph(_sanitize_xml(paren_text), style))

            elif element_type == "dialogue":
                style = ParagraphStyle(
                    f"ScreenplayDialogue_{idx}",
                    fontName=cfg.font_name_pdf,
                    fontSize=cfg.font_size_pt,
                    leading=cfg.leading_pt,
                    alignment=0,
                    leftIndent=cfg.dialogue_left_in * inch,
                    rightIndent=cfg.dialogue_right_in * inch,
                    spaceBefore=space_before,
                    spaceAfter=space_after,
                    textColor=colors.black,
                )
                story.append(Paragraph(_sanitize_xml(clean_text), style))

            elif element_type == "transition":
                style = ParagraphStyle(
                    f"ScreenplayTransition_{idx}",
                    fontName=cfg.font_name_pdf_bold,
                    fontSize=cfg.font_size_pt,
                    leading=cfg.leading_pt,
                    alignment=2,
                    spaceBefore=space_before,
                    spaceAfter=space_after,
                    textColor=colors.black,
                )
                run_text = clean_text if is_rejected else clean_text.upper()
                story.append(Paragraph(_sanitize_xml(run_text), style))

            elif element_type == "end":
                style = ParagraphStyle(
                    f"ScreenplayEnd_{idx}",
                    fontName=cfg.font_name_pdf_bold,
                    fontSize=cfg.font_size_pt,
                    leading=cfg.leading_pt,
                    alignment=1,
                    spaceBefore=space_before,
                    spaceAfter=space_after,
                    textColor=colors.black,
                )
                run_text = clean_text if is_rejected else clean_text.upper()
                story.append(Paragraph(_sanitize_xml(run_text), style))

            elif element_type == "shot":
                style = ParagraphStyle(
                    f"ScreenplayShot_{idx}",
                    fontName=cfg.font_name_pdf_bold,
                    fontSize=cfg.font_size_pt,
                    leading=cfg.leading_pt,
                    alignment=0,
                    leftIndent=cfg.shot_left_in * inch,
                    rightIndent=cfg.shot_right_in * inch,
                    spaceBefore=space_before,
                    spaceAfter=space_after,
                    keepWithNext=True,
                    textColor=colors.black,
                )
                run_text = clean_text if is_rejected else clean_text.upper()
                story.append(Paragraph(_sanitize_xml(run_text), style))

            else:  # action, uncertain, or other
                style = ParagraphStyle(
                    f"ScreenplayAction_{idx}",
                    fontName=cfg.font_name_pdf,
                    fontSize=cfg.font_size_pt,
                    leading=cfg.leading_pt,
                    alignment=0,
                    leftIndent=cfg.action_left_in * inch,
                    rightIndent=cfg.action_right_in * inch,
                    spaceBefore=space_before,
                    spaceAfter=space_after,
                    textColor=colors.black,
                )
                story.append(Paragraph(_sanitize_xml(clean_text), style))

        def _draw_screenplay_page_num(canvas, doc_obj):
            page_num = canvas.getPageNumber()
            if page_num > 1:
                canvas.saveState()
                canvas.setFont("Courier", 12)
                canvas.drawRightString(7.5 * inch, 10.4 * inch, f"{page_num}.")
                canvas.restoreState()

        doc.build(story, onFirstPage=lambda c, d: None, onLaterPages=_draw_screenplay_page_num)
        buffer.seek(0)
        logger.info("screenplay_pdf_generated")
        return buffer.getvalue()


    def generate_tariff_memo(
        self,
        workspace_name: str,
        document_name: str = "Workflow Output",
        sections: Optional[List[Dict[str, Any]]] = None,
        images: Optional[List[Dict[str, Any]]] = None,
    ) -> bytes:
        """
        Generate a canonical Tariff Classification Memo as PDF with professional typography and layout.

        Includes:
          - Document Header and Metadata (Workspace, Date, Document)
          - Numbered Sections with content
          - Analyst Reasoning
          - Alternative Classifications Table
          - Source Attributions / Citations
          - Structured Recommendation Callout Card
          - Embedded product images
          - Dynamic two-pass page numbering ("Page X of Y")
        """
        logger.info("generating_tariff_memo_pdf", section_count=len(sections or []))

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
        )

        title_style = ParagraphStyle(
            "TariffTitle",
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#1F3864"),
            spaceBefore=0,
            spaceAfter=2,
            keepWithNext=True,
        )

        subtitle_style = ParagraphStyle(
            "TariffSubtitle",
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=15,
            textColor=colors.HexColor("#2B4C7E"),
            spaceBefore=0,
            spaceAfter=4,
            keepWithNext=True,
        )

        meta_style = ParagraphStyle(
            "TariffMeta",
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#4B5563"),
            spaceBefore=0,
            spaceAfter=6,
            keepWithNext=True,
        )

        h1_style = ParagraphStyle(
            "TariffH1",
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=16,
            textColor=colors.HexColor("#1F3864"),
            spaceBefore=12,
            spaceAfter=3,
            keepWithNext=True,
        )

        h2_style = ParagraphStyle(
            "TariffH2",
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=14,
            textColor=colors.HexColor("#2B4C7E"),
            spaceBefore=8,
            spaceAfter=2,
            keepWithNext=True,
        )

        body_style = ParagraphStyle(
            "TariffBody",
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#1F2937"),
            spaceBefore=0,
            spaceAfter=4.5,
        )

        citation_style = ParagraphStyle(
            "TariffCitation",
            fontName="Helvetica-Oblique",
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#4B5563"),
            leftIndent=14,
            spaceBefore=0,
            spaceAfter=2.5,
        )

        caption_style = ParagraphStyle(
            "TariffCaption",
            fontName="Helvetica-Oblique",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#6B7280"),
            alignment=1,  # Centered
            spaceBefore=2,
            spaceAfter=6,
        )

        story = []

        # 1. Header Title Block
        story.append(Paragraph("TARIFF CLASSIFICATION MEMORANDUM", title_style))
        story.append(Paragraph(f"Subject Merchandise: {_sanitize_xml(document_name)}", subtitle_style))
        date_str = datetime.now().strftime("%B %d, %Y")
        story.append(
            Paragraph(
                f"Date: {date_str}   |   Workspace: {_sanitize_xml(workspace_name)}   |   Source File: {_sanitize_xml(document_name)}",
                meta_style,
            )
        )
        story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1F3864"), spaceBefore=2, spaceAfter=8))

        sorted_sections = sorted(sections or [], key=lambda s: s.get("section_order", 0))
        recommendation_rendered = False
        latest_recommendation = None
        alternatives_rendered = False
        latest_alternatives = None
        images_rendered = False

        for sec in sorted_sections:
            struct = sec.get("structured_data") or {}
            if isinstance(struct, dict):
                if struct.get("recommendation"):
                    latest_recommendation = struct["recommendation"]
                if struct.get("alternatives"):
                    latest_alternatives = struct["alternatives"]

        # 2. Render Sections
        for section in sorted_sections:
            if section.get("status") == "skipped":
                continue

            sec_title = section.get("title", "Section")
            sec_type = section.get("section_type", "")
            content = section.get("content", "")
            reasoning = section.get("analyst_reasoning")
            attributions = section.get("source_attribution", [])
            structured_data = section.get("structured_data", {})

            story.append(Paragraph(_sanitize_xml(sec_title), h1_style))

            # Render main content paragraphs
            if content:
                for para in content.split("\n\n"):
                    clean_para = para.strip()
                    if clean_para:
                        story.append(Paragraph(_sanitize_xml(clean_para), body_style))

            # Render analyst reasoning if distinct and non-trivial
            reasoning_str = (reasoning or "").strip()
            content_str = (content or "").strip()
            if (
                reasoning_str
                and reasoning_str.lower() != content_str.lower()
                and reasoning_str.lower() not in ("reasoning:", "reasoning", "analyst reasoning:", "analyst reasoning")
                and len(reasoning_str) >= 5
            ):
                story.append(Paragraph("Analyst Reasoning", h2_style))
                for r_para in reasoning_str.split("\n\n"):
                    clean_r = r_para.strip()
                    if clean_r:
                        story.append(Paragraph(_sanitize_xml(clean_r), body_style))

            # Render alternative classifications table if present in alternative sections or section with alternatives
            is_alt_sec = "alternative" in sec_title.lower() or sec_type in ("alternatives_considered", "alternatives_rejected")
            if structured_data and isinstance(structured_data, dict):
                alts = structured_data.get("alternatives")
                alts_to_render = alts if is_alt_sec else (alts if not alternatives_rendered else None)
                if alts_to_render and isinstance(alts_to_render, list) and not alternatives_rendered:
                    alt_table_flowable = self._build_pdf_alternatives_table(alts_to_render, h2_style)
                    if alt_table_flowable:
                        story.append(alt_table_flowable)
                        alternatives_rendered = True

            # Render source attributions with enhanced styling
            if attributions:
                story.append(Paragraph("Sources & Evidence", h2_style))
                for attr in attributions:
                    parts = []
                    doc_name = attr.get("document_name") or attr.get("document_id")
                    ruling = attr.get("ruling_number") or attr.get("ruling")
                    if doc_name:
                        parts.append(f"Document: {doc_name}")
                    elif ruling:
                        parts.append(f"Ruling: {ruling}")
                    page = attr.get("page")
                    if page is not None:
                        parts.append(f"Page {page}")
                    excerpt = attr.get("excerpt", "")
                    if excerpt:
                        if len(excerpt) > 180:
                            excerpt = excerpt[:180] + "..."
                        parts.append(f'"{excerpt}"')
                    citation_text = "   |   ".join(parts)
                    if citation_text:
                        story.append(Paragraph(f"• &nbsp; {_sanitize_xml(citation_text)}", citation_style))

            # Render structured recommendation callout card ONLY in the Final Recommended Classification section
            is_rec_sec = "recommended" in sec_title.lower() or sec_type == "recommended_classification"
            if is_rec_sec:
                rec = (structured_data.get("recommendation") if isinstance(structured_data, dict) else None) or latest_recommendation
                if rec and isinstance(rec, dict):
                    rec_card = self._build_pdf_recommendation_card(rec, body_style)
                    if rec_card:
                        story.append(rec_card)
                        recommendation_rendered = True

            # Render product images if this is the product_images section
            is_img_sec = "image" in sec_title.lower() or sec_type == "product_images"
            if is_img_sec and images:
                images_rendered = True
                for img in images:
                    img_bytes = img.get("bytes")
                    filename = img.get("filename", "image")
                    if img_bytes:
                        try:
                            img_obj = RLImage(BytesIO(img_bytes), width=4.2 * inch, height=2.8 * inch)
                            cap_obj = Paragraph(f"Figure: {_sanitize_xml(filename)}", caption_style)
                            story.append(KeepTogether([Spacer(1, 4), img_obj, cap_obj, Spacer(1, 4)]))
                        except Exception as e:
                            logger.warning("pdf_image_embed_error", filename=filename, error=str(e))

            story.append(Spacer(1, 4))

        if latest_alternatives and not alternatives_rendered:
            story.append(Paragraph("Alternative Classifications Considered", h1_style))
            alt_table_flowable = self._build_pdf_alternatives_table(latest_alternatives, h2_style)
            if alt_table_flowable:
                story.append(alt_table_flowable)

        if images and not images_rendered:
            story.append(Paragraph("Product Images", h1_style))
            for img in images:
                img_bytes = img.get("bytes")
                filename = img.get("filename", "image")
                if img_bytes:
                    try:
                        img_obj = RLImage(BytesIO(img_bytes), width=4.2 * inch, height=2.8 * inch)
                        cap_obj = Paragraph(f"Figure: {_sanitize_xml(filename)}", caption_style)
                        story.append(KeepTogether([Spacer(1, 4), img_obj, cap_obj, Spacer(1, 4)]))
                    except Exception as e:
                        logger.warning("pdf_image_embed_error", filename=filename, error=str(e))

        if latest_recommendation and not recommendation_rendered:
            story.append(Paragraph("Final Recommended Classification", h1_style))
            rec_card = self._build_pdf_recommendation_card(latest_recommendation, body_style)
            if rec_card:
                story.append(rec_card)

        doc.build(story, canvasmaker=NumberedMemoCanvas)
        buffer.seek(0)
        logger.info("tariff_memo_pdf_generated")
        return buffer.getvalue()

    def _build_pdf_recommendation_card(self, rec: Dict[str, Any], body_style: ParagraphStyle) -> KeepTogether:
        """Build a prominent callout card for recommended classification determination."""
        hs_code = rec.get("hs_code", "N/A")
        desc = rec.get("description", "")
        duty = rec.get("duty_rate")
        reasoning = rec.get("reasoning", "")

        card_title_style = ParagraphStyle(
            "RecCardTitle",
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=14,
            textColor=colors.HexColor("#1F3864"),
            spaceBefore=0,
            spaceAfter=3,
        )

        card_body_style = ParagraphStyle(
            "RecCardBody",
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#1F2937"),
            spaceBefore=1,
            spaceAfter=2,
        )

        lines = [
            Paragraph("RECOMMENDED CLASSIFICATION DETERMINATION", card_title_style),
            Paragraph(f"<b>Recommended HS Code:</b> &nbsp;<font color=\"#1F3864\"><b>{_sanitize_xml(str(hs_code))}</b></font>", card_body_style),
        ]
        if desc:
            lines.append(Paragraph(f"<b>Official Description:</b> {_sanitize_xml(str(desc))}", card_body_style))
        if duty:
            lines.append(Paragraph(f"<b>General Duty Rate:</b> {_sanitize_xml(str(duty))}", card_body_style))
        if reasoning:
            lines.append(Paragraph(f"<b>Legal Rationale:</b> {_sanitize_xml(str(reasoning))}", card_body_style))

        table_data = [[lines]]
        card_table = Table(table_data, colWidths=[6.8 * inch])
        card_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
            ('BOX', (0,0), (-1,-1), 0.75, colors.HexColor("#CBD5E1")),
            ('LINELEFT', (0,0), (0,-1), 3.5, colors.HexColor("#1F3864")),
            ('TOPPADDING', (0,0), (-1,-1), 7),
            ('BOTTOMPADDING', (0,0), (-1,-1), 7),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))
        return KeepTogether([Spacer(1, 3), card_table, Spacer(1, 4)])

    def _build_pdf_alternatives_table(self, alternatives: List[Dict[str, Any]], h2_style: ParagraphStyle) -> Optional[KeepTogether]:
        """Build a clean table for alternative classifications considered."""
        if not alternatives:
            return None

        th_style = ParagraphStyle(
            "AltTH",
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.white,
        )
        td_hs_style = ParagraphStyle(
            "AltTD_HS",
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10.5,
            textColor=colors.HexColor("#1F3864"),
        )
        td_style = ParagraphStyle(
            "AltTD",
            fontName="Helvetica",
            fontSize=8,
            leading=10.5,
            textColor=colors.HexColor("#1F2937"),
        )

        table_rows = [
            [
                Paragraph("<b>Candidate HS Code</b>", th_style),
                Paragraph("<b>Description</b>", th_style),
                Paragraph("<b>Rejection Rationale</b>", th_style),
            ]
        ]
        for alt in alternatives:
            candidate_hs = alt.get("candidate_hs") or alt.get("hs_code") or "N/A"
            desc = alt.get("description") or ""
            rejection = alt.get("rejection_reason") or alt.get("supporting_arguments") or ""
            table_rows.append([
                Paragraph(f"<b>{_sanitize_xml(str(candidate_hs))}</b>", td_hs_style),
                Paragraph(_sanitize_xml(str(desc)), td_style),
                Paragraph(_sanitize_xml(str(rejection)), td_style),
            ])

        alt_table = Table(table_rows, colWidths=[1.4 * inch, 2.3 * inch, 3.1 * inch])
        alt_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1F3864")),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#F8FAFC")]),
        ]))
        return KeepTogether([Paragraph("Alternative Classifications Table", h2_style), Spacer(1, 2), alt_table, Spacer(1, 4)])

    def generate_tariff_report(
        self,
        workspace_name: str,
        document_name: str,
        claims: List[Dict[str, Any]],
        generated_report: str,
    ) -> bytes:
        """Generate a review summary report as PDF."""
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
        )

        title_style = ParagraphStyle(
            "ReportTitle",
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#1F3864"),
        )
        h1_style = ParagraphStyle(
            "ReportH1",
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=colors.HexColor("#1F3864"),
            spaceBefore=12,
            spaceAfter=6,
        )
        body_style = ParagraphStyle(
            "ReportBody",
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            spaceAfter=6,
        )

        story = [
            Paragraph("Tariff Classification Report", title_style),
            Spacer(1, 6),
            Paragraph(f"<b>Workspace:</b> {_sanitize_xml(workspace_name)} &nbsp;|&nbsp; <b>Document:</b> {_sanitize_xml(document_name)}", body_style),
            Spacer(1, 10),
            HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CCCCCC"), spaceAfter=12),
        ]

        if generated_report:
            story.append(Paragraph("Classification Output", h1_style))
            for p in generated_report.split("\n\n"):
                if p.strip():
                    story.append(Paragraph(_sanitize_xml(p.strip()), body_style))

        if claims:
            story.append(Paragraph("Review Claims", h1_style))
            for claim in claims:
                status = claim.get("status", "pending")
                content = claim.get("content", "")
                story.append(Paragraph(f"&bull; [{status.upper()}] {_sanitize_xml(content)}", body_style))

        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()
