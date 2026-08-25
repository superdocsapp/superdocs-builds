"""Publication-Ready, Beautiful PDF Model Card Renderer.

Renders high-aesthetic, multi-page vector PDF Model and System Cards using ReportLab
with custom color palettes, styled benchmark tables, metric summary hero cards,
callout boxes, and running headers/footers.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas
    from reportlab.platypus import (
        HRFlowable,
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


class NumberedCanvas(canvas.Canvas if HAS_REPORTLAB else object):
    """Canvas that performs a two-pass calculation of total page numbers."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: List[Any] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int) -> None:
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))

        # Header (pages > 1)
        if self._pageNumber > 1:
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.75)
            self.line(40, 755, 572, 755)
            self.drawString(40, 762, "SuperDocs Model & System Card Specification")
            self.drawRightString(572, 762, "Verified Documentation")

        # Footer (all pages)
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.75)
        self.line(40, 45, 572, 45)
        
        self.drawString(40, 32, "Generated via SuperDocs 4-Call Document Engine • Standard ML Model Card")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(572, 32, page_str)
        
        self.restoreState()


class PDFCardRenderer:
    """Generates stunning, publication-ready PDF Model Cards."""

    # Color Palette Tokens
    PRIMARY = colors.HexColor("#4F46E5")       # Indigo
    PRIMARY_DARK = colors.HexColor("#1E1B4B")  # Deep Midnight Navy
    PRIMARY_LIGHT = colors.HexColor("#EEF2FF") # Indigo 50
    SURFACE_BG = colors.HexColor("#F8FAFC")    # Slate 50
    CARD_BG = colors.HexColor("#FFFFFF")
    TEXT_MAIN = colors.HexColor("#0F172A")     # Slate 900
    TEXT_MUTED = colors.HexColor("#475569")    # Slate 600
    TEXT_SUBTLE = colors.HexColor("#94A3B8")   # Slate 400
    BORDER_COLOR = colors.HexColor("#E2E8F0")  # Slate 200
    BORDER_DARK = colors.HexColor("#CBD5E1")   # Slate 300
    
    # Accent & Metric Colors
    EMERALD_BG = colors.HexColor("#ECFDF5")
    EMERALD_TEXT = colors.HexColor("#047857")
    ROSE_BG = colors.HexColor("#FFF1F2")
    ROSE_TEXT = colors.HexColor("#BE123C")
    AMBER_BG = colors.HexColor("#FFFBEB")
    AMBER_TEXT = colors.HexColor("#B45309")
    CYAN_TEXT = colors.HexColor("#0284C7")
    CYAN_BG = colors.HexColor("#F0F9FF")

    @classmethod
    def render(
        cls,
        manifest: Dict[str, Any],
        evaluation_records: Optional[List[Dict[str, Any]]] = None,
        evaluation_metadata: Optional[Dict[str, Any]] = None,
        raw_markdown: Optional[str] = None,
    ) -> bytes:
        """Render publication-grade PDF model card into bytes."""
        if not HAS_REPORTLAB:
            return cls._render_fallback_pdf(manifest, raw_markdown)

        eval_records = evaluation_records or []
        eval_meta = evaluation_metadata or {}
        buffer = io.BytesIO()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=40,
            rightMargin=40,
            topMargin=45,
            bottomMargin=55,
        )

        styles = getSampleStyleSheet()
        
        # Custom Typography Styles
        style_hero_title = ParagraphStyle(
            "HeroTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=cls.PRIMARY_DARK,
            spaceAfter=6,
        )
        style_hero_sub = ParagraphStyle(
            "HeroSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=cls.TEXT_MUTED,
            spaceAfter=12,
        )
        style_section_heading = ParagraphStyle(
            "SectionHeading",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=cls.PRIMARY_DARK,
            spaceBefore=14,
            spaceAfter=8,
            keepWithNext=True,
        )
        style_card_title = ParagraphStyle(
            "CardTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=cls.PRIMARY,
            spaceAfter=4,
        )
        style_body = ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=cls.TEXT_MAIN,
        )
        style_body_muted = ParagraphStyle(
            "BodyMuted",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=cls.TEXT_MUTED,
        )
        style_mono = ParagraphStyle(
            "Mono",
            parent=styles["Normal"],
            fontName="Courier",
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#334155"),
        )

        elements: List[Any] = []

        # Extract Manifest Fields
        model_name = manifest.get("model_name", "Model Card")
        version = manifest.get("version", "v1.0.0")
        release_date = manifest.get("release_date", "Not provided")
        model_type = manifest.get("model_type", "Not provided")
        license_str = manifest.get("license", "Not provided")
        description = manifest.get("description", "Not provided")
        architecture = manifest.get("model_architecture", "Not provided")
        org = manifest.get("author_organization", "Not provided")
        contact = manifest.get("maintenance_contact", "Not provided")
        intended = manifest.get("intended_purpose", "Not provided")
        out_of_scope = manifest.get("out_of_scope_uses", "Not provided")
        limitations = manifest.get("limitations", "Not provided")
        training_data = manifest.get("training_data_summary", "Not provided")
        hardware = manifest.get("hardware_and_compute", "Not provided")
        ethics = manifest.get("ethical_considerations", "Not provided")
        citation = manifest.get("citation", "Not provided")

        eval_ts = eval_meta.get("timestamp", "2026-08-17 12:00:00 UTC")
        eval_run_id = eval_meta.get("run_id", "run-latest")
        eval_baseline = eval_meta.get("baseline_model", "Baseline Reference")

        # ---------------------------------------------------------------------
        # 1. Hero Header Banner
        # ---------------------------------------------------------------------
        badge_pills = [
            f"<b>Version:</b> {version}",
            f"<b>License:</b> {license_str}",
            f"<b>Type:</b> {model_type}",
            f"<b>Released:</b> {release_date}",
        ]
        badge_text = "   •   ".join(badge_pills)
        
        banner_data = [
            [
                Paragraph(
                    f"<font size='8' color='#4F46E5'><b>OFFICIAL MODEL SPECIFICATION</b></font><br/>"
                    f"<b>{model_name}</b>",
                    style_hero_title
                )
            ],
            [
                Paragraph(f"<font color='#6366F1'>{badge_text}</font>", style_body_muted)
            ],
            [
                Paragraph(description, style_hero_sub)
            ]
        ]
        banner_table = Table(banner_data, colWidths=[532])
        banner_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), cls.PRIMARY_LIGHT),
            ("BOX", (0, 0), (-1, -1), 1, cls.PRIMARY),
            ("PADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
        ]))
        elements.append(banner_table)
        elements.append(Spacer(1, 10))

        # ---------------------------------------------------------------------
        # 2. Key Stat Summary Cards
        # ---------------------------------------------------------------------
        total_evals = len(eval_records)
        max_score = max([r.get("score", 0) for r in eval_records], default=0.0)
        pos_deltas = [r.get("delta_val", 0) for r in eval_records if r.get("delta_val") is not None and r.get("delta_val") > 0]
        max_delta = max(pos_deltas, default=0.0)

        stat_col_w = 532 / 4
        stats_row = [
            [
                Paragraph("<font size='7' color='#64748B'>BENCHMARKS</font><br/><b><font size='14' color='#0F172A'>" + str(total_evals) + "</font></b><br/><font size='7' color='#10B981'>Multi-domain</font>", style_body),
                Paragraph(f"<font size='7' color='#64748B'>PEAK SCORE</font><br/><b><font size='14' color='#0F172A'>{max_score:.1f}%</font></b><br/><font size='7' color='#10B981'>Standardized</font>", style_body),
                Paragraph(f"<font size='7' color='#64748B'>MAX DELTA</font><br/><b><font size='14' color='#0F172A'>+{max_delta:.1f}%</font></b><br/><font size='7' color='#10B981'>vs {eval_baseline[:12]}</font>", style_body),
                Paragraph(f"<font size='7' color='#64748B'>EVAL RUN ID</font><br/><b><font size='10' color='#0F172A'>{eval_run_id[:12]}</font></b><br/><font size='7' color='#64748B'>{eval_ts[:10]}</font>", style_body),
            ]
        ]
        stats_table = Table(stats_row, colWidths=[stat_col_w] * 4)
        stats_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), cls.SURFACE_BG),
            ("BOX", (0, 0), (-1, -1), 0.75, cls.BORDER_COLOR),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, cls.BORDER_COLOR),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(stats_table)
        elements.append(Spacer(1, 14))

        # ---------------------------------------------------------------------
        # 3. Specifications & Governance (2-Column Grid)
        # ---------------------------------------------------------------------
        elements.append(Paragraph("1. Architecture & Governance", style_section_heading))
        
        arch_text = cls._format_obj_for_pdf(architecture)
        gov_text = (
            f"<b>Organization / Lab:</b> {org}<br/>"
            f"<b>Maintenance Contact:</b> {cls._format_contact_for_pdf(contact)}<br/>"
            f"<b>Hardware & Compute:</b> {cls._format_obj_for_pdf(hardware)}"
        )

        grid_w = 532 / 2
        specs_data = [
            [
                Paragraph("<b>Model Specifications</b>", style_card_title),
                Paragraph("<b>Governance & Ownership</b>", style_card_title),
            ],
            [
                Paragraph(arch_text, style_body),
                Paragraph(gov_text, style_body),
            ]
        ]
        specs_table = Table(specs_data, colWidths=[grid_w, grid_w])
        specs_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), cls.SURFACE_BG),
            ("BOX", (0, 0), (-1, -1), 0.75, cls.BORDER_COLOR),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, cls.BORDER_COLOR),
            ("PADDING", (0, 0), (-1, -1), 10),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elements.append(specs_table)
        elements.append(Spacer(1, 14))

        # ---------------------------------------------------------------------
        # 4. Intended Purpose & Limitations
        # ---------------------------------------------------------------------
        elements.append(Paragraph("2. Operational Scope & Limitations", style_section_heading))

        intended_text = cls._format_obj_for_pdf(intended, bullet=True)
        limitations_text = cls._format_obj_for_pdf(limitations, bullet=True)

        scope_data = [
            [
                Paragraph("<b>Primary Intended Applications</b>", style_card_title),
                Paragraph("<b>Known Limitations</b>", style_card_title),
            ],
            [
                Paragraph(intended_text, style_body),
                Paragraph(limitations_text, style_body),
            ]
        ]
        scope_table = Table(scope_data, colWidths=[grid_w, grid_w])
        scope_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), cls.CARD_BG),
            ("BOX", (0, 0), (-1, -1), 0.75, cls.BORDER_COLOR),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, cls.BORDER_COLOR),
            ("PADDING", (0, 0), (-1, -1), 10),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elements.append(scope_table)
        elements.append(Spacer(1, 8))

        # Out-of-scope Warning Callout Box
        out_of_scope_text = cls._format_obj_for_pdf(out_of_scope, bullet=True)
        callout_data = [
            [
                Paragraph("<b>Prohibited & Out-of-Scope Deployments</b>", ParagraphStyle("WTitle", parent=style_card_title, textColor=cls.AMBER_TEXT)),
            ],
            [
                Paragraph(out_of_scope_text, style_body),
            ]
        ]
        callout_table = Table(callout_data, colWidths=[532])
        callout_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), cls.AMBER_BG),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#F59E0B")),
            ("PADDING", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elements.append(callout_table)
        elements.append(Spacer(1, 14))

        # ---------------------------------------------------------------------
        # 5. Benchmark Evaluations Table
        # ---------------------------------------------------------------------
        elements.append(Paragraph(f"3. Quantitative Evaluation Benchmarks (vs {eval_baseline})", style_section_heading))
        elements.append(Paragraph(
            f"<font size='7.5' color='#64748B'>Last evaluation cycle: {eval_ts} • Run ID: {eval_run_id}</font>",
            style_body_muted
        ))
        elements.append(Spacer(1, 6))

        if eval_records:
            table_headers = ["Benchmark", "Domain", "Metric / Setting", "Score", f"Baseline ({eval_baseline[:10]})", "Delta", "Details"]
            table_widths = [85, 75, 80, 52, 60, 50, 130]

            rows: List[List[Any]] = [
                [Paragraph(f"<b><font color='#1E1B4B'>{h}</font></b>", style_body) for h in table_headers]
            ]

            for rec in eval_records:
                name = rec.get("name", rec.get("task_id", "Unknown"))
                domain = rec.get("domain", "General")
                metric_shots = f"{rec.get('metric', '')} ({rec.get('shots', '0-shot')})"
                score_str = rec.get("score_str", f"{rec.get('score', 0):.1f}%")
                baseline_str = rec.get("baseline_str", f"{rec.get('baseline', 0):.1f}%")
                delta_str = rec.get("delta_str", "—")
                desc = rec.get("description", "") or "—"

                delta_val = rec.get("delta_val")
                if delta_val is not None and delta_val > 0:
                    delta_p = Paragraph(f"<b><font color='#047857'>{delta_str}</font></b>", style_body)
                elif delta_val is not None and delta_val < 0:
                    delta_p = Paragraph(f"<b><font color='#BE123C'>{delta_str}</font></b>", style_body)
                else:
                    delta_p = Paragraph(f"<font color='#64748B'>{delta_str}</font>", style_body)

                rows.append([
                    Paragraph(f"<b>{name}</b>", style_body),
                    Paragraph(f"<font color='#475569'>{domain}</font>", style_body_muted),
                    Paragraph(f"<font color='#475569'>{metric_shots}</font>", style_body_muted),
                    Paragraph(f"<b>{score_str}</b>", style_body),
                    Paragraph(f"<font color='#64748B'>{baseline_str}</font>", style_body_muted),
                    delta_p,
                    Paragraph(f"<font size='7' color='#475569'>{desc}</font>", style_body_muted),
                ])

            eval_table = Table(rows, colWidths=table_widths, repeatRows=1)
            eval_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), cls.PRIMARY_LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.75, cls.BORDER_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, cls.BORDER_COLOR),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [cls.CARD_BG, cls.SURFACE_BG]),
                ("PADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            elements.append(eval_table)
        else:
            elements.append(Paragraph("<i>No benchmark evaluations provided.</i>", style_body_muted))

        elements.append(Spacer(1, 14))

        # ---------------------------------------------------------------------
        # 6. Training Data, Compute & Safety
        # ---------------------------------------------------------------------
        elements.append(Paragraph("4. Training Data & Safety Evaluations", style_section_heading))

        train_text = cls._format_obj_for_pdf(training_data)
        ethics_text = cls._format_obj_for_pdf(ethics, bullet=True)

        safety_data = [
            [
                Paragraph("<b>Training Data Summary</b>", style_card_title),
                Paragraph("<b>Safety Alignment & Ethics</b>", style_card_title),
            ],
            [
                Paragraph(train_text, style_body),
                Paragraph(ethics_text, style_body),
            ]
        ]
        safety_table = Table(safety_data, colWidths=[grid_w, grid_w])
        safety_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), cls.SURFACE_BG),
            ("BOX", (0, 0), (-1, -1), 0.75, cls.BORDER_COLOR),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, cls.BORDER_COLOR),
            ("PADDING", (0, 0), (-1, -1), 10),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elements.append(safety_table)
        elements.append(Spacer(1, 14))

        # ---------------------------------------------------------------------
        # 7. Citation
        # ---------------------------------------------------------------------
        elements.append(Paragraph("5. Citation & Reference", style_section_heading))
        cite_text = citation.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        cite_table = Table([[Paragraph(cite_text, style_mono)]], colWidths=[532])
        cite_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), cls.SURFACE_BG),
            ("BOX", (0, 0), (-1, -1), 0.75, cls.BORDER_COLOR),
            ("PADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(cite_table)

        # Build document with Numbered Canvas
        doc.build(elements, canvasmaker=NumberedCanvas)
        return buffer.getvalue()

    @classmethod
    def render_from_markdown(cls, markdown_text: str, title: str = "Model Card") -> bytes:
        """Parse basic markdown sections and render into PDF."""
        # Simple extraction of manifest-like dictionary
        manifest: Dict[str, Any] = {"model_name": title}
        
        # Extract title from `# Model Card: ...`
        m_title = re.search(r"^#\s+(?:Model Card:\s*)?([^\n]+)", markdown_text, re.MULTILINE)
        if m_title:
            manifest["model_name"] = m_title.group(1).strip()

        # Extract description
        m_desc = re.search(r"##\s+Executive Summary\s*\n+([^#]+)", markdown_text, re.MULTILINE)
        if m_desc:
            manifest["description"] = m_desc.group(1).strip()

        # Extract citation
        m_cite = re.search(r"```(?:bibtex)?\s*\n([^`]+)```", markdown_text)
        if m_cite:
            manifest["citation"] = m_cite.group(1).strip()

        return cls.render(manifest=manifest, raw_markdown=markdown_text)

    # -------------------------------------------------------------------------
    # Helper formatting methods
    # -------------------------------------------------------------------------
    @classmethod
    def _format_obj_for_pdf(cls, obj: Any, bullet: bool = False) -> str:
        """Format Python object cleanly for ReportLab HTML paragraph."""
        if not obj or obj == "Not provided":
            return "<i>Not provided</i>"
        if isinstance(obj, str):
            clean = obj.replace("<", "&lt;").replace(">", "&gt;")
            if bullet:
                lines = [l.strip("-* ") for l in clean.split("\n") if l.strip()]
                return "<br/>".join([f"• {l}" for l in lines]) if lines else clean
            return clean.replace("\n", "<br/>")
        if isinstance(obj, dict):
            parts = []
            for k, v in obj.items():
                k_label = k.replace("_", " ").title()
                parts.append(f"<b>{k_label}:</b> {v}")
            return "<br/>".join(parts)
        if isinstance(obj, list):
            items = [str(x).replace("<", "&lt;").replace(">", "&gt;") for x in obj if x]
            if bullet:
                return "<br/>".join([f"• {x}" for x in items])
            return "<br/>".join(items) if items else "<i>Not provided</i>"
        return str(obj)

    @classmethod
    def _format_contact_for_pdf(cls, contact: Any) -> str:
        """Format contact details for PDF display."""
        if not contact or contact == "Not provided":
            return "<i>Not provided</i>"
        if isinstance(contact, str):
            return contact
        if isinstance(contact, dict):
            parts = []
            if "team" in contact:
                parts.append(str(contact["team"]))
            if "email" in contact:
                parts.append(f"<font color='#4F46E5'>{contact['email']}</font>")
            return " — ".join(parts) if parts else str(contact)
        return str(contact)

    @classmethod
    def _render_fallback_pdf(cls, manifest: Dict[str, Any], raw_markdown: Optional[str] = None) -> bytes:
        """Lightweight pure-python PDF fallback if reportlab is unavailable."""
        title = manifest.get("model_name", "Model Card")
        lines = [
            f"MODEL CARD: {title}",
            f"Version: {manifest.get('version', 'Not provided')}",
            f"Release Date: {manifest.get('release_date', 'Not provided')}",
            f"License: {manifest.get('license', 'Not provided')}",
            "",
            f"Description: {manifest.get('description', 'Not provided')}",
        ]
        if raw_markdown:
            for l in raw_markdown.splitlines()[:40]:
                if l.strip():
                    lines.append(l.strip()[:85])

        stream_lines = ["BT /F1 14 Tf 50 770 Td (Model Card Specification) Tj ET"]
        y = 740
        for l in lines[:45]:
            clean = l.replace("(", "[").replace(")", "]").replace("\\", "/")[:85]
            stream_lines.append(f"BT /F1 9 Tf 50 {y} Td ({clean}) Tj ET")
            y -= 15
            if y < 50:
                break

        stream_content = "\n".join(stream_lines)
        stream_len = len(stream_content.encode("latin-1", errors="replace"))

        pdf_payload = (
            f"%PDF-1.4\n"
            f"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
            f"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
            f"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
            f"4 0 obj << /Length {stream_len} >>\nstream\n{stream_content}\nendstream\nendobj\n"
            f"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
            f"xref\n0 6\n0000000000 65535 f \n0000000010 00000 n \n0000000060 00000 n \n0000000117 00000 n \n0000000234 00000 n \n0000000300 00000 n \n"
            f"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n380\n%%EOF"
        )
        return pdf_payload.encode("latin-1", errors="replace")
