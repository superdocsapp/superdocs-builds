from io import BytesIO
from typing import List, Dict, Any, Optional
from datetime import datetime
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from backend.logging_config import get_logger
from backend.core.export.screenplay_layout import (
    DEFAULT_SCREENPLAY_LAYOUT,
    calculate_element_spacing,
)

logger = get_logger(__name__)


def _set_cell_background(cell, fill_hex: str) -> None:
    """Set background color of a table cell in DOCX."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill_hex)
    tcPr.append(shd)


def _set_cell_margins(cell, top: int = 140, bottom: int = 140, left: int = 200, right: int = 200) -> None:
    """Set inner padding of a table cell in twentieths of a point (dxa)."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for edge, val in (('top', top), ('bottom', bottom), ('left', left), ('right', right)):
        node = OxmlElement(f'w:{edge}')
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)


def _set_callout_borders(cell, color_hex: str = "1F3864") -> None:
    """Set a thick left border and subtle borders on a callout cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    
    left = OxmlElement('w:left')
    left.set(qn('w:val'), 'single')
    left.set(qn('w:sz'), '24')  # 3pt
    left.set(qn('w:space'), '0')
    left.set(qn('w:color'), color_hex)
    tcBorders.append(left)

    for edge in ('top', 'bottom', 'right'):
        b = OxmlElement(f'w:{edge}')
        b.set(qn('w:val'), 'single')
        b.set(qn('w:sz'), '4')  # 0.5pt
        b.set(qn('w:space'), '0')
        b.set(qn('w:color'), 'CBD5E1')
        tcBorders.append(b)
        
    tcPr.append(tcBorders)


def _add_memo_footer(section, title_text: str = "Tariff Classification Memo") -> None:
    """Add professional subtle footer with document title and dynamic page number."""
    try:
        footer = section.footer
        footer_p = footer.paragraphs[0]
        footer_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        footer_p.paragraph_format.space_before = Pt(6)
        footer_p.paragraph_format.space_after = Pt(0)
        
        run_left = footer_p.add_run(f"{title_text}   |   Page ")
        run_left.font.name = "Calibri"
        run_left.font.size = Pt(8.5)
        run_left.font.color.rgb = RGBColor(110, 110, 110)

        fldChar1 = OxmlElement('w:fldChar')
        fldChar1.set(qn('w:fldCharType'), 'begin')
        instrText = OxmlElement('w:instrText')
        instrText.set(qn('xml:space'), 'preserve')
        instrText.text = "PAGE"
        fldChar2 = OxmlElement('w:fldChar')
        fldChar2.set(qn('w:fldCharType'), 'separate')
        fldChar3 = OxmlElement('w:fldChar')
        fldChar3.set(qn('w:fldCharType'), 'end')

        run_page = footer_p.add_run()
        run_page.font.name = "Calibri"
        run_page.font.size = Pt(8.5)
        run_page.font.color.rgb = RGBColor(110, 110, 110)
        run_page._r.append(fldChar1)
        run_page._r.append(instrText)
        run_page._r.append(fldChar2)
        run_page._r.append(fldChar3)
    except Exception as e:
        logger.warning("failed_to_add_docx_memo_footer", error=str(e))


def _add_docx_page_number_to_header(section):
    """Add dynamic page numbering to header for pages 2+ in screenplay format ('2.')."""
    try:
        section.different_first_page_header_footer = True
        header = section.header
        header_p = header.paragraphs[0]
        header_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        header_p.paragraph_format.space_before = Pt(0)
        header_p.paragraph_format.space_after = Pt(0)

        run = header_p.add_run()
        run.font.name = "Courier New"
        run.font.size = Pt(12)
        run.font.color.rgb = RGBColor(0, 0, 0)

        fldChar1 = OxmlElement('w:fldChar')
        fldChar1.set(qn('w:fldCharType'), 'begin')
        instrText = OxmlElement('w:instrText')
        instrText.set(qn('xml:space'), 'preserve')
        instrText.text = "PAGE"
        fldChar2 = OxmlElement('w:fldChar')
        fldChar2.set(qn('w:fldCharType'), 'separate')
        fldChar3 = OxmlElement('w:fldChar')
        fldChar3.set(qn('w:fldCharType'), 'end')

        run._r.append(fldChar1)
        run._r.append(instrText)
        run._r.append(fldChar2)
        run._r.append(fldChar3)

        dot_run = header_p.add_run(".")
        dot_run.font.name = "Courier New"
        dot_run.font.size = Pt(12)
        dot_run.font.color.rgb = RGBColor(0, 0, 0)
    except Exception as e:
        logger.warning("failed_to_add_docx_header_page_num", error=str(e))



class DOCXGenerator:
    """
    Generate DOCX documents from structured data.

    Used for exporting workflow results, review summaries, etc.
    """

    def __init__(self):
        self.document = Document()
        self._setup_styles()

    def _setup_styles(self):
        """Setup document styles"""
        # Modify existing styles
        styles = self.document.styles

        # Title style
        title_style = styles['Title']
        title_font = title_style.font
        title_font.size = Pt(24)
        title_font.bold = True
        title_font.color.rgb = RGBColor(31, 56, 100)

        # Heading 1 style
        h1_style = styles['Heading 1']
        h1_font = h1_style.font
        h1_font.size = Pt(18)
        h1_font.color.rgb = RGBColor(31, 56, 100)

    def add_title(self, text: str) -> None:
        """Add document title"""
        title = self.document.add_heading(text, level=0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def add_heading(self, text: str, level: int = 1) -> None:
        """Add section heading with keep_with_next to avoid orphan headings."""
        p = self.document.add_heading(text, level=level)
        p.paragraph_format.keep_with_next = True

    def add_paragraph(self, text: str, bold: bool = False, italic: bool = False) -> None:
        """Add paragraph with optional formatting"""
        p = self.document.add_paragraph(text)
        if bold or italic:
            run = p.runs[0]
            run.bold = bold
            run.italic = italic

    def add_table(self, headers: List[str], rows: List[List[str]]) -> None:
        """Add table with headers and data rows"""
        table = self.document.add_table(rows=1 + len(rows), cols=len(headers))
        table.style = 'Light Grid Accent 1'

        # Add headers
        hdr_cells = table.rows[0].cells
        for i, header in enumerate(headers):
            hdr_cells[i].text = header
            # Make header bold
            for paragraph in hdr_cells[i].paragraphs:
                for run in paragraph.runs:
                    run.bold = True

        # Add data rows
        for i, row_data in enumerate(rows):
            row_cells = table.rows[i + 1].cells
            for j, cell_data in enumerate(row_data):
                row_cells[j].text = str(cell_data)

    def add_key_value_pair(self, key: str, value: str) -> None:
        """Add key-value pair formatted as 'Key: Value'"""
        p = self.document.add_paragraph()
        p.add_run(f"{key}: ").bold = True
        p.add_run(value)

    def add_page_break(self) -> None:
        """Add page break"""
        self.document.add_page_break()

    def generate_tariff_report(
        self,
        workspace_name: str,
        document_name: str,
        claims: List[Dict[str, Any]],
        generated_report: str
    ) -> bytes:
        """
        Generate tariff classification report.

        Args:
            workspace_name: Name of workspace
            document_name: Source document name
            claims: List of tariff claims
            generated_report: Generated report text

        Returns:
            DOCX file as bytes
        """
        logger.info("generating_tariff_docx", claims_count=len(claims))

        # Title
        self.add_title("Tariff Classification Report")

        # Metadata
        self.add_paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.add_paragraph(f"Workspace: {workspace_name}")
        self.add_paragraph(f"Source Document: {document_name}")
        self.add_paragraph("")  # Blank line

        # Executive Summary
        self.add_heading("Executive Summary", level=1)
        self.add_paragraph(f"This report contains tariff classification for {len(claims)} product(s).")
        self.add_paragraph("")

        # Claims Table
        self.add_heading("Tariff Classifications", level=1)

        if claims:
            headers = ["HS Code", "Description", "Duty Rate", "Status"]
            rows = []
            for claim in claims:
                # Parse claim content (assuming JSON format)
                import json
                try:
                    content = json.loads(claim.get("content", "{}"))
                except:
                    content = {"hs_code": "N/A", "description": "N/A", "duty_rate": "N/A"}

                rows.append([
                    content.get("hs_code", "N/A"),
                    content.get("description", "N/A"),
                    content.get("duty_rate", "N/A"),
                    claim.get("status", "pending")
                ])

            self.add_table(headers, rows)
        else:
            self.add_paragraph("No classifications found.")

        self.add_paragraph("")

        # Generated Report
        if generated_report:
            self.add_heading("Detailed Analysis", level=1)
            # Split report into paragraphs
            for paragraph in generated_report.split('\n'):
                if paragraph.strip():
                    self.add_paragraph(paragraph.strip())

        # Footer
        self.add_page_break()
        self.add_heading("Notes", level=1)
        self.add_paragraph(
            "This report is generated automatically and should be reviewed by a qualified customs specialist."
        )

        # Save to bytes
        from io import BytesIO
        buffer = BytesIO()
        self.document.save(buffer)
        buffer.seek(0)

        logger.info("tariff_docx_generated")
        return buffer.getvalue()

    def generate_tariff_memo(
        self,
        workspace_name: str,
        document_name: str,
        sections: List[Dict[str, Any]],
        images: Optional[List[Dict[str, Any]]] = None,
    ) -> bytes:
        """
        Generate structured tariff classification memo DOCX with professional typography and layout.

        Args:
            workspace_name: Workspace name
            document_name: Primary document name
            sections: List of memo sections with content
            images: Optional list of images with {"bytes": bytes, "filename": str}

        Returns:
            DOCX file as bytes
        """
        logger.info("generating_tariff_memo_docx", sections_count=len(sections))

        # 1. Configure page margins and footer
        for section_obj in self.document.sections:
            section_obj.top_margin = Inches(1.0)
            section_obj.bottom_margin = Inches(1.0)
            section_obj.left_margin = Inches(1.0)
            section_obj.right_margin = Inches(1.0)
            _add_memo_footer(section_obj, "Tariff Classification Memo")

        # 2. Render Header Title Block
        self._render_memo_header(workspace_name, document_name)

        # 3. Render Sections in canonical order
        recommendation_rendered = False
        latest_recommendation = None
        alternatives_rendered = False
        latest_alternatives = None
        images_rendered = False

        sorted_sections = sorted(sections, key=lambda s: s.get("section_order", 0))

        for sec in sorted_sections:
            struct = sec.get("structured_data") or {}
            if struct.get("recommendation"):
                latest_recommendation = struct["recommendation"]
            if struct.get("alternatives"):
                latest_alternatives = struct["alternatives"]

        for section in sorted_sections:
            if section.get("status") == "skipped":
                continue

            sec_title = section.get("title", "Section")
            sec_type = section.get("section_type", "")
            self._add_memo_heading(sec_title, level=1)

            # Render main content paragraphs
            if section.get("content"):
                for paragraph in section["content"].split("\n"):
                    clean_p = paragraph.strip()
                    if clean_p:
                        self._add_memo_paragraph(clean_p)
                self._add_memo_spacing(Pt(3))

            # Render analyst reasoning if distinct and non-trivial
            reasoning = (section.get("analyst_reasoning") or "").strip()
            content_str = (section.get("content") or "").strip()
            if (
                reasoning
                and reasoning.lower() != content_str.lower()
                and reasoning.lower() not in ("reasoning:", "reasoning", "analyst reasoning:", "analyst reasoning")
                and len(reasoning) >= 5
            ):
                self._add_memo_heading("Analyst Reasoning", level=2)
                for para in reasoning.split("\n"):
                    clean_r = para.strip()
                    if clean_r:
                        self._add_memo_paragraph(clean_r)
                self._add_memo_spacing(Pt(3))

            # Render alternative classifications table if present in alternative sections or section with alternatives
            structured = section.get("structured_data") or {}
            is_alt_sec = "alternative" in sec_title.lower() or sec_type in ("alternatives_considered", "alternatives_rejected")
            alts_to_render = structured.get("alternatives") if is_alt_sec else (structured.get("alternatives") if not alternatives_rendered else None)
            if alts_to_render and not alternatives_rendered:
                self._render_alternatives_table(alts_to_render)
                alternatives_rendered = True
                self._add_memo_spacing(Pt(3))

            # Render source attributions with enhanced styling
            source_attrs = section.get("source_attribution") or []
            if source_attrs:
                self._add_memo_heading("Sources & Evidence", level=2)
                for attr in source_attrs:
                    self._render_source_attribution(attr)
                self._add_memo_spacing(Pt(3))

            # Render structured recommendation callout block ONLY in the Final Recommended Classification section
            is_rec_sec = "recommended" in sec_title.lower() or sec_type == "recommended_classification"
            if is_rec_sec:
                rec_data = structured.get("recommendation") or latest_recommendation
                if rec_data:
                    self._render_recommendation(rec_data)
                    recommendation_rendered = True
                    self._add_memo_spacing(Pt(4))

            # Render product images if this is the product_images section
            is_img_sec = "image" in sec_title.lower() or sec_type == "product_images"
            if is_img_sec and images:
                self._render_images(images)
                images_rendered = True
                self._add_memo_spacing(Pt(4))

        if latest_alternatives and not alternatives_rendered:
            self._add_memo_heading("Alternative Classifications Considered", level=1)
            self._render_alternatives_table(latest_alternatives)
            self._add_memo_spacing(Pt(3))

        if images and not images_rendered:
            self._add_memo_heading("Product Images", level=1)
            self._render_images(images)
            self._add_memo_spacing(Pt(4))

        if latest_recommendation and not recommendation_rendered:
            self._add_memo_heading("Final Recommended Classification", level=1)
            self._render_recommendation(latest_recommendation)
            self._add_memo_spacing(Pt(4))

        from io import BytesIO
        buffer = BytesIO()
        self.document.save(buffer)
        buffer.seek(0)
        logger.info("tariff_memo_docx_generated")
        return buffer.getvalue()

    def _render_memo_header(self, workspace_name: str, document_name: str) -> None:
        """Render a clean, professional header block on the first page."""
        # Main Title
        p_title = self.document.add_paragraph()
        p_title.paragraph_format.space_before = Pt(0)
        p_title.paragraph_format.space_after = Pt(2)
        p_title.paragraph_format.keep_with_next = True
        p_title.paragraph_format.widow_control = True
        r_title = p_title.add_run("Tariff Classification Memo")
        r_title.bold = True
        r_title.font.name = "Calibri"
        r_title.font.size = Pt(18)
        r_title.font.color.rgb = RGBColor(0x1F, 0x38, 0x64)

        # Subject Merchandise Subtitle
        p_sub = self.document.add_paragraph()
        p_sub.paragraph_format.space_before = Pt(0)
        p_sub.paragraph_format.space_after = Pt(4)
        p_sub.paragraph_format.keep_with_next = True
        p_sub.paragraph_format.widow_control = True
        r_sub = p_sub.add_run(f"Subject Merchandise: {document_name}")
        r_sub.bold = True
        r_sub.font.name = "Calibri"
        r_sub.font.size = Pt(11.5)
        r_sub.font.color.rgb = RGBColor(0x2B, 0x4C, 0x7E)

        # Metadata Line
        date_str = datetime.now().strftime("%B %d, %Y")
        p_meta = self.document.add_paragraph()
        p_meta.paragraph_format.space_before = Pt(0)
        p_meta.paragraph_format.space_after = Pt(6)
        p_meta.paragraph_format.keep_with_next = True
        p_meta.paragraph_format.widow_control = True
        
        meta_run = p_meta.add_run(f"Date: {date_str}   |   Workspace: {workspace_name}   |   Source File: {document_name}")
        meta_run.font.name = "Calibri"
        meta_run.font.size = Pt(9)
        meta_run.font.color.rgb = RGBColor(110, 110, 110)

        # Accent Divider Line Table
        tbl = self.document.add_table(rows=1, cols=1)
        tbl.autofit = False
        tbl.columns[0].width = Inches(6.5)
        c = tbl.rows[0].cells[0]
        c.width = Inches(6.5)
        _set_cell_background(c, "1F3864")
        _set_cell_margins(c, top=10, bottom=10, left=0, right=0)
        p_empty = c.paragraphs[0]
        p_empty.paragraph_format.space_before = Pt(0)
        p_empty.paragraph_format.space_after = Pt(0)
        r_empty = p_empty.add_run("")
        r_empty.font.size = Pt(1)

        p_sp = self.document.add_paragraph()
        p_sp.paragraph_format.space_before = Pt(4)
        p_sp.paragraph_format.space_after = Pt(4)

    def _add_memo_heading(self, text: str, level: int = 1) -> None:
        """Add memo section heading with consistent typography and keep_with_next."""
        p = self.document.add_heading(text, level=level)
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.widow_control = True

        for run in p.runs:
            run.bold = True
            run.font.name = "Calibri"

            if level == 1:
                p.paragraph_format.space_before = Pt(12)
                p.paragraph_format.space_after = Pt(3)
                run.font.size = Pt(13)
                run.font.color.rgb = RGBColor(0x1F, 0x38, 0x64)
            elif level == 2:
                p.paragraph_format.space_before = Pt(8)
                p.paragraph_format.space_after = Pt(2)
                run.font.size = Pt(11)
                run.font.color.rgb = RGBColor(0x2B, 0x4C, 0x7E)
            else:
                p.paragraph_format.space_before = Pt(6)
                p.paragraph_format.space_after = Pt(2)
                run.font.size = Pt(10)
                run.font.color.rgb = RGBColor(0x37, 0x41, 0x51)


    def _add_memo_paragraph(self, text: str, bold: bool = False, italic: bool = False) -> None:
        """Add styled body paragraph with standard typography."""
        p = self.document.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(4.5)
        p.paragraph_format.line_spacing = 1.15
        p.paragraph_format.widow_control = True

        run = p.add_run(text)
        run.font.name = "Calibri"
        run.font.size = Pt(10.5)
        run.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
        run.bold = bold
        run.italic = italic

    def _add_memo_spacing(self, pts: Pt) -> None:
        """Add subtle vertical spacing."""
        p = self.document.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = pts
        r = p.add_run("")
        r.font.size = Pt(1)

    def _render_source_attribution(self, attr: Dict[str, Any]) -> None:
        """Render a single source attribution with clean indented bullet formatting."""
        parts = []

        doc_name = attr.get("document_name")
        doc_id = attr.get("document_id")
        ruling = attr.get("ruling_number") or attr.get("ruling")

        if doc_name:
            parts.append(f"Document: {doc_name}")
        elif doc_id:
            parts.append(f"Document ID: {doc_id}")
        elif ruling:
            parts.append(f"Ruling: {ruling}")

        page = attr.get("page")
        if page is not None:
            parts.append(f"Page: {page}")

        excerpt = attr.get("excerpt", "")
        if excerpt:
            if len(excerpt) > 200:
                excerpt = excerpt[:200] + "..."
            parts.append(f'"{excerpt}"')

        if parts:
            citation = "   |   ".join(parts)
            p = self.document.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.2)
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(2.5)
            p.paragraph_format.widow_control = True
            
            bullet_run = p.add_run("•  ")
            bullet_run.font.name = "Calibri"
            bullet_run.font.size = Pt(8.5)
            bullet_run.font.color.rgb = RGBColor(0x1F, 0x38, 0x64)
            
            text_run = p.add_run(citation)
            text_run.font.name = "Calibri"
            text_run.font.size = Pt(8.5)
            text_run.italic = True
            text_run.font.color.rgb = RGBColor(90, 90, 90)

    def _render_recommendation(self, rec: Dict[str, Any]) -> None:
        """Render structured recommendation as a prominent, professional callout card."""
        hs_code = rec.get("hs_code", "N/A")
        description = rec.get("description", "")
        duty_rate = rec.get("duty_rate", "")
        reasoning = rec.get("reasoning", "")

        table = self.document.add_table(rows=1, cols=1)
        table.autofit = False
        table.columns[0].width = Inches(6.5)

        # Prevent row split across pages
        trPr = table.rows[0]._tr.get_or_add_trPr()
        trPr.append(OxmlElement('w:cantSplit'))

        cell = table.rows[0].cells[0]
        cell.width = Inches(6.5)
        _set_cell_background(cell, "F8FAFC")
        _set_cell_margins(cell, top=140, bottom=140, left=180, right=180)
        _set_callout_borders(cell, color_hex="1F3864")

        # Card Title
        p_card_title = cell.paragraphs[0]
        p_card_title.paragraph_format.space_before = Pt(0)
        p_card_title.paragraph_format.space_after = Pt(4)
        p_card_title.paragraph_format.keep_with_next = True
        r_card_title = p_card_title.add_run("RECOMMENDED CLASSIFICATION DETERMINATION")
        r_card_title.bold = True
        r_card_title.font.name = "Calibri"
        r_card_title.font.size = Pt(11)
        r_card_title.font.color.rgb = RGBColor(0x1F, 0x38, 0x64)

        # HS Code
        p_hs = cell.add_paragraph()
        p_hs.paragraph_format.space_before = Pt(2)
        p_hs.paragraph_format.space_after = Pt(3)
        p_hs.paragraph_format.keep_with_next = True
        r_hs_lbl = p_hs.add_run("Recommended HS Code: ")
        r_hs_lbl.bold = True
        r_hs_lbl.font.name = "Calibri"
        r_hs_lbl.font.size = Pt(10)
        r_hs_val = p_hs.add_run(str(hs_code))
        r_hs_val.bold = True
        r_hs_val.font.name = "Calibri"
        r_hs_val.font.size = Pt(10.5)
        r_hs_val.font.color.rgb = RGBColor(0x1F, 0x38, 0x64)

        if description:
            p_desc = cell.add_paragraph()
            p_desc.paragraph_format.space_before = Pt(2)
            p_desc.paragraph_format.space_after = Pt(3)
            p_desc.paragraph_format.keep_with_next = True
            r_desc_lbl = p_desc.add_run("Official Description: ")
            r_desc_lbl.bold = True
            r_desc_lbl.font.name = "Calibri"
            r_desc_lbl.font.size = Pt(10)
            r_desc_val = p_desc.add_run(str(description))
            r_desc_val.font.name = "Calibri"
            r_desc_val.font.size = Pt(10)

        if duty_rate:
            p_duty = cell.add_paragraph()
            p_duty.paragraph_format.space_before = Pt(2)
            p_duty.paragraph_format.space_after = Pt(3)
            p_duty.paragraph_format.keep_with_next = True
            r_duty_lbl = p_duty.add_run("General Duty Rate: ")
            r_duty_lbl.bold = True
            r_duty_lbl.font.name = "Calibri"
            r_duty_lbl.font.size = Pt(10)
            r_duty_val = p_duty.add_run(str(duty_rate))
            r_duty_val.font.name = "Calibri"
            r_duty_val.font.size = Pt(10)

        if reasoning:
            p_reas = cell.add_paragraph()
            p_reas.paragraph_format.space_before = Pt(4)
            p_reas.paragraph_format.space_after = Pt(2)
            p_reas.paragraph_format.keep_with_next = True
            r_reas_lbl = p_reas.add_run("Legal Rationale: ")
            r_reas_lbl.bold = True
            r_reas_lbl.font.name = "Calibri"
            r_reas_lbl.font.size = Pt(10)
            r_reas_val = p_reas.add_run(str(reasoning))
            r_reas_val.font.name = "Calibri"
            r_reas_val.font.size = Pt(10)

    def _render_alternatives_table(self, alternatives: List[Dict[str, Any]]) -> None:
        """Render alternative classifications considered as a clean table."""
        if not alternatives:
            return
        self._add_memo_heading("Alternative Classifications Table", level=2)
        headers = ["Candidate HS Code", "Description", "Rejection Rationale"]
        table = self.document.add_table(rows=1 + len(alternatives), cols=3)
        table.style = 'Table Grid'

        # Header row
        hdr_row = table.rows[0]
        hdr_tr = hdr_row._tr.get_or_add_trPr()
        hdr_tr.append(OxmlElement('w:cantSplit'))
        hdr_tr.append(OxmlElement('w:tblHeader'))

        col_widths = [Inches(1.5), Inches(2.2), Inches(2.8)]
        for i, header in enumerate(headers):
            cell = hdr_row.cells[i]
            cell.width = col_widths[i]
            _set_cell_background(cell, "1F3864")
            _set_cell_margins(cell, top=80, bottom=80, left=100, right=100)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            run = p.add_run(header)
            run.bold = True
            run.font.name = "Calibri"
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        # Data rows
        for idx, alt in enumerate(alternatives):
            row = table.rows[idx + 1]
            row_tr = row._tr.get_or_add_trPr()
            row_tr.append(OxmlElement('w:cantSplit'))
            bg_color = "F8FAFC" if idx % 2 == 1 else "FFFFFF"

            row_data = [
                alt.get("candidate_hs") or alt.get("hs_code") or "N/A",
                alt.get("description") or "",
                alt.get("rejection_reason") or alt.get("supporting_arguments") or "",
            ]
            for col_i, text_val in enumerate(row_data):
                cell = row.cells[col_i]
                cell.width = col_widths[col_i]
                _set_cell_background(cell, bg_color)
                _set_cell_margins(cell, top=60, bottom=60, left=80, right=80)
                p = cell.paragraphs[0]
                p.paragraph_format.space_before = Pt(1)
                p.paragraph_format.space_after = Pt(1)
                run = p.add_run(str(text_val))
                run.font.name = "Calibri"
                run.font.size = Pt(8.5)
                if col_i == 0:
                    run.bold = True
                    run.font.color.rgb = RGBColor(0x1F, 0x38, 0x64)

    def _render_images(self, images: List[Dict[str, Any]]) -> None:
        """Render product images with centered layout, aspect ratio preservation, and attached captions."""
        from io import BytesIO

        for img in images:
            img_bytes = img.get("bytes")
            filename = img.get("filename", "image")

            if not img_bytes:
                p_unavail = self.document.add_paragraph()
                p_unavail.paragraph_format.keep_with_next = True
                p_unavail.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = p_unavail.add_run(f"[Image unavailable: {filename}]")
                run.italic = True
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor(120, 120, 120)
                continue

            try:
                # Add picture paragraph centered with keep_with_next
                img_p = self.document.add_paragraph()
                img_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                img_p.paragraph_format.space_before = Pt(8)
                img_p.paragraph_format.space_after = Pt(2)
                img_p.paragraph_format.keep_with_next = True
                img_p.paragraph_format.widow_control = True

                run_img = img_p.add_run()
                run_img.add_picture(BytesIO(img_bytes), width=Inches(4.2))

                # Add caption directly below image
                caption_p = self.document.add_paragraph()
                caption_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                caption_p.paragraph_format.space_before = Pt(2)
                caption_p.paragraph_format.space_after = Pt(8)
                caption_p.paragraph_format.widow_control = True
                caption_run = caption_p.add_run(f"Figure: {filename}")
                caption_run.italic = True
                caption_run.font.name = "Calibri"
                caption_run.font.size = Pt(8.5)
                caption_run.font.color.rgb = RGBColor(100, 100, 100)
            except Exception as e:
                logger.warning(
                    "image_embedding_failed",
                    filename=filename,
                    error=str(e),
                )
                err_p = self.document.add_paragraph(f"[Image: {filename}]")
                err_p.alignment = WD_ALIGN_PARAGRAPH.CENTER


    def generate_screenplay_docx(
        self,
        formatting_items: List[Dict[str, Any]],
        title: str = "Untitled Screenplay",
        workspace_name: str = "",
    ) -> bytes:

        """
        Generate a DOCX with industry-standard screenplay formatting.

        Conforms to standard screenplay layout:
          - US Letter (8.5" x 11")
          - Margins: Left 1.5", Right 1.0", Top 1.0", Bottom 1.0"
          - Courier New 12pt monospace font throughout
          - Elements: TITLE, AUTHOR/CREDIT, SCENE_HEADING, ACTION,
            CHARACTER, PARENTHETICAL, DIALOGUE, TRANSITION, SHOT, END
          - Professional pagination: keep-with-next on headings/characters/parentheticals,
            widow control, header page numbering (p. 2+)
          - No generic document header or workspace metadata
          - Review status: approved/pending uses formatted_text, rejected uses original_text
        """
        logger.info("generating_screenplay_docx", item_count=len(formatting_items))

        # Create a dedicated clean document with standard screenplay page setup
        doc = Document()
        section = doc.sections[0]
        cfg = DEFAULT_SCREENPLAY_LAYOUT
        section.page_width = Inches(cfg.page_width_in)
        section.page_height = Inches(cfg.page_height_in)
        section.top_margin = Inches(cfg.margin_top_in)
        section.bottom_margin = Inches(cfg.margin_bottom_in)
        section.left_margin = Inches(cfg.margin_left_in)
        section.right_margin = Inches(cfg.margin_right_in)

        # Set base Normal style to Courier New 12pt Black
        normal_style = doc.styles["Normal"]
        normal_style.font.name = cfg.font_name_docx
        normal_style.font.size = Pt(cfg.font_size_pt)
        normal_style.font.color.rgb = RGBColor(0, 0, 0)

        # Configure header page numbering (pages 2+)
        _add_docx_page_number_to_header(section)

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
            p = doc.add_paragraph()
            p.paragraph_format.line_spacing = cfg.line_spacing
            p.paragraph_format.widow_control = True

            is_rejected = (status == "rejected")
            prev_item = valid_items[idx - 1] if idx > 0 else None
            next_item = valid_items[idx + 1] if idx + 1 < len(valid_items) else None
            prev_type = prev_item.get("element_type") if prev_item else None
            next_type = next_item.get("element_type") if next_item else None

            space_before, space_after = calculate_element_spacing(element_type, prev_type, next_type, cfg)
            p.paragraph_format.space_before = Pt(space_before)
            p.paragraph_format.space_after = Pt(space_after)

            if element_type == "title":
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = p.add_run(clean_text)
                run.bold = True
                run.font.name = cfg.font_name_docx
                run.font.size = Pt(cfg.font_size_pt)
                run.font.color.rgb = RGBColor(0, 0, 0)

            elif element_type in ("author", "author_credit", "credit"):
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = p.add_run(clean_text)
                run.bold = False
                run.font.name = cfg.font_name_docx
                run.font.size = Pt(cfg.font_size_pt)
                run.font.color.rgb = RGBColor(0, 0, 0)

            elif element_type == "scene_heading":
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                p.paragraph_format.left_indent = Inches(cfg.scene_heading_left_in)
                p.paragraph_format.right_indent = Inches(cfg.scene_heading_right_in)
                p.paragraph_format.keep_with_next = True
                run_text = clean_text if is_rejected else clean_text.upper()
                run = p.add_run(run_text)
                run.bold = True
                run.font.name = cfg.font_name_docx
                run.font.size = Pt(cfg.font_size_pt)
                run.font.color.rgb = RGBColor(0, 0, 0)

            elif element_type == "character":
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                p.paragraph_format.left_indent = Inches(cfg.character_left_in)
                p.paragraph_format.right_indent = Inches(cfg.character_right_in)
                p.paragraph_format.keep_with_next = True
                p.paragraph_format.keep_together = True
                run_text = clean_text if is_rejected else clean_text.upper()
                run = p.add_run(run_text)
                run.bold = True
                run.font.name = cfg.font_name_docx
                run.font.size = Pt(cfg.font_size_pt)
                run.font.color.rgb = RGBColor(0, 0, 0)

            elif element_type == "parenthetical":
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                p.paragraph_format.left_indent = Inches(cfg.parenthetical_left_in)
                p.paragraph_format.right_indent = Inches(cfg.parenthetical_right_in)
                p.paragraph_format.keep_with_next = True
                p.paragraph_format.keep_together = True
                if is_rejected:
                    paren_text = clean_text
                else:
                    paren_text = clean_text
                    if not paren_text.startswith("("):
                        paren_text = "(" + paren_text
                    if not paren_text.endswith(")"):
                        paren_text = paren_text + ")"
                run = p.add_run(paren_text)
                run.bold = False
                run.font.name = cfg.font_name_docx
                run.font.size = Pt(cfg.font_size_pt)
                run.font.color.rgb = RGBColor(0, 0, 0)

            elif element_type == "dialogue":
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                p.paragraph_format.left_indent = Inches(cfg.dialogue_left_in)
                p.paragraph_format.right_indent = Inches(cfg.dialogue_right_in)
                # Keep short dialogue paragraphs intact, allow long ones to break naturally
                if len(clean_text) <= 180:
                    p.paragraph_format.keep_together = True
                run = p.add_run(clean_text)
                run.bold = False
                run.font.name = cfg.font_name_docx
                run.font.size = Pt(cfg.font_size_pt)
                run.font.color.rgb = RGBColor(0, 0, 0)

            elif element_type == "transition":
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                p.paragraph_format.keep_together = True
                run_text = clean_text if is_rejected else clean_text.upper()
                run = p.add_run(run_text)
                run.bold = True
                run.font.name = cfg.font_name_docx
                run.font.size = Pt(cfg.font_size_pt)
                run.font.color.rgb = RGBColor(0, 0, 0)

            elif element_type == "end":
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.keep_together = True
                run_text = clean_text if is_rejected else clean_text.upper()
                run = p.add_run(run_text)
                run.bold = True
                run.font.name = cfg.font_name_docx
                run.font.size = Pt(cfg.font_size_pt)
                run.font.color.rgb = RGBColor(0, 0, 0)

            elif element_type == "shot":
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                p.paragraph_format.left_indent = Inches(cfg.shot_left_in)
                p.paragraph_format.right_indent = Inches(cfg.shot_right_in)
                p.paragraph_format.keep_with_next = True
                p.paragraph_format.keep_together = True
                run_text = clean_text if is_rejected else clean_text.upper()
                run = p.add_run(run_text)
                run.bold = True
                run.font.name = cfg.font_name_docx
                run.font.size = Pt(cfg.font_size_pt)
                run.font.color.rgb = RGBColor(0, 0, 0)

            else:  # action, uncertain, or other
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                p.paragraph_format.left_indent = Inches(cfg.action_left_in)
                p.paragraph_format.right_indent = Inches(cfg.action_right_in)
                # Keep short action paragraphs together, allow longer ones to break naturally
                if len(clean_text) <= 200:
                    p.paragraph_format.keep_together = True
                run = p.add_run(clean_text)
                run.bold = False
                run.font.name = cfg.font_name_docx
                run.font.size = Pt(cfg.font_size_pt)
                run.font.color.rgb = RGBColor(0, 0, 0)

        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        logger.info("screenplay_docx_generated")
        return buffer.getvalue()

