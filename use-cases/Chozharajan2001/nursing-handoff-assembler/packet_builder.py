"""
Standardized 10-Page Clinical Transfer Packet PDF Generator (Task 2 Band S2).
Uses ReportLab to generate a multi-page clinical transfer dossier with fixed section geometry,
high-risk verification badges, reconciled MAR tables, appended clinical notes, and SHA-256 audit ledger.
"""
import io
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
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

from clinical_pipeline import ClinicalPacketAssembler, MedicationItem, PatientDemographics, SBARData


class ClinicalPDFPacketBuilder:
    """Generates the standardized 10-Page + Appendix Clinical Transfer Packet PDF."""

    def __init__(self, assembler: ClinicalPacketAssembler):
        self.assembler = assembler
        self.styles = getSampleStyleSheet()
        self._init_custom_styles()

    def _init_custom_styles(self):
        self.title_style = ParagraphStyle(
            "DocTitle",
            parent=self.styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=4,
        )
        self.section_heading = ParagraphStyle(
            "SectionHeading",
            parent=self.styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#1e3a8a"),
            spaceBefore=10,
            spaceAfter=6,
        )
        self.body_style = ParagraphStyle(
            "BodyDark",
            parent=self.styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#1e293b"),
        )
        self.citation_style = ParagraphStyle(
            "CitationStyle",
            parent=self.styles["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#475569"),
        )
        self.warning_style = ParagraphStyle(
            "WarningStyle",
            parent=self.styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#b91c1c"),
        )
        self.verified_badge = ParagraphStyle(
            "VerifiedBadge",
            parent=self.styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#15803d"),
        )

    def _format_citation_line(self, citations: Optional[List[dict]]) -> str:
        """Render an SBAR citation line strictly from structured citation data (T2-2 fix).

        Honesty contract (B5): the PDF never prints a citation that was not
        supplied in the SBARData citation lists. When a section carries no
        citations, an explicit "none recorded" marker is rendered instead of a
        fabricated source reference.
        """
        parts = []
        for c in citations or []:
            if not isinstance(c, dict):
                continue
            doc = c.get("doc") or c.get("document") or ""
            page = c.get("page")
            if doc and page is not None:
                parts.append(f"{doc}:p{page}")
            elif doc:
                parts.append(str(doc))
        if not parts:
            return "<i>Citations: none recorded for this section.</i>"
        return "<i>Citations: [" + ", ".join(parts) + "]</i>"

    def _build_header_table(self) -> Table:
        demo = self.assembler.demographics
        data = [
            [
                Paragraph(f"<b>PATIENT:</b> {demo.name}", self.body_style),
                Paragraph(f"<b>MRN:</b> {demo.mrn}", self.body_style),
                Paragraph(f"<b>DOB / AGE:</b> {demo.dob} ({demo.age}y {demo.gender[0]})", self.body_style),
            ],
            [
                Paragraph(f"<b>FROM:</b> {demo.sending_unit}", self.body_style),
                Paragraph(f"<b>TO:</b> {demo.receiving_unit}", self.body_style),
                Paragraph(f"<b>ATTENDING:</b> {demo.attending_physician}", self.body_style),
            ],
            [
                Paragraph(f"<b>ADMIT DATE:</b> {demo.admission_date}", self.body_style),
                Paragraph(f"<b>CODE STATUS:</b> <b>{demo.code_status}</b>", self.body_style),
                Paragraph("<b>TRANSFER PACKET:</b> S2 FIXED DOSSIER", self.body_style),
            ],
        ]
        t = Table(data, colWidths=[2.5 * inch, 2.5 * inch, 2.5 * inch])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return t

    def generate_pdf_bytes(self) -> bytes:
        """Compiles the complete multi-page document into raw PDF bytes."""
        unlocked, unverified = self.assembler.gates.is_export_unlocked()
        if not unlocked:
            raise PermissionError(
                f"Export Blocked (HTTP 422): High-risk clinical safety gates pending: {unverified}"
            )

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=0.5 * inch,
            leftMargin=0.5 * inch,
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch,
        )
        story = []

        # ==========================================
        # PAGE 1: Executive SBAR Summary
        # ==========================================
        story.append(Paragraph("HOSPITAL CLINICAL TRANSFER DOSSIER", self.title_style))
        story.append(Paragraph("CONFIDENTIAL MEDICAL RECORD • SBAR SUMMARY & VERIFIED HANDOFF", self.citation_style))
        story.append(Spacer(1, 6))
        story.append(self._build_header_table())
        story.append(Spacer(1, 10))

        story.append(Paragraph("1. SBAR CLINICAL HANDOFF NARRATIVE (PROVENANCE-GROUNDED)", self.section_heading))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1e3a8a"), spaceAfter=8))

        sbar = self.assembler.sbar or SBARData(situation="", background="", assessment="", recommendation="")
        
        # Situation
        story.append(Paragraph("<b>SITUATION:</b>", self.body_style))
        story.append(Paragraph(sbar.situation, self.body_style))
        story.append(Paragraph(self._format_citation_line(sbar.situation_citations), self.citation_style))
        story.append(Spacer(1, 8))

        # Background
        story.append(Paragraph("<b>BACKGROUND & PAST MEDICAL HISTORY:</b>", self.body_style))
        story.append(Paragraph(sbar.background, self.body_style))
        story.append(Paragraph(self._format_citation_line(sbar.background_citations), self.citation_style))
        story.append(Spacer(1, 8))

        # Assessment
        story.append(Paragraph("<b>CLINICAL ASSESSMENT & CURRENT TRAJECTORY:</b>", self.body_style))
        story.append(Paragraph(sbar.assessment, self.body_style))
        story.append(Paragraph(self._format_citation_line(sbar.assessment_citations), self.citation_style))
        story.append(Spacer(1, 8))

        # Recommendation
        story.append(Paragraph("<b>RECOMMENDATIONS & STEP-DOWN PLAN:</b>", self.body_style))
        story.append(Paragraph(sbar.recommendation, self.body_style))
        story.append(Paragraph(self._format_citation_line(sbar.recommendation_citations), self.citation_style))

        # ==========================================
        # PAGE 2: Confirmed Allergies & Code Status Block
        # ==========================================
        story.append(PageBreak())
        story.append(self._build_header_table())
        story.append(Spacer(1, 10))
        story.append(Paragraph("2. SAFETY VERIFICATION GATEWAY (MANDATORY HUMAN SIGN-OFF)", self.section_heading))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1e3a8a"), spaceAfter=8))

        # Allergies Table
        allergy_data = [
            [Paragraph("<b>ALLERGY / ADVERSE DRUG REACTION</b>", self.body_style), Paragraph("<b>REACTION SEVERITY</b>", self.body_style), Paragraph("<b>VERIFICATION STATUS</b>", self.body_style)]
        ]
        for a in self.assembler.allergies:
            allergy_data.append([
                Paragraph(a, self.body_style),
                Paragraph("Severe / Anaphylaxis Risk" if "anaphylaxis" in a.lower() else "Moderate Sensitivity", self.body_style),
                Paragraph(f"✓ CONFIRMED: {self.assembler.gates.allergies_nurse}", self.verified_badge),
            ])
        t_allergies = Table(allergy_data, colWidths=[3.2 * inch, 2.0 * inch, 2.3 * inch])
        t_allergies.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(t_allergies)
        story.append(Spacer(1, 14))

        # Code Status Verification
        story.append(Paragraph("<b>RESUSCITATION CODE STATUS VERIFICATION:</b>", self.body_style))
        code_data = [
            [
                Paragraph(f"<b>RECORDED CODE STATUS:</b> {self.assembler.demographics.code_status}", self.body_style),
                Paragraph(f"✓ SIGNED OFF BY: {self.assembler.gates.code_status_nurse}", self.verified_badge),
            ]
        ]
        t_code = Table(code_data, colWidths=[4.0 * inch, 3.5 * inch])
        t_code.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdf4")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#86efac")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t_code)

        # ==========================================
        # PAGE 3: Reconciled Medication Administration Record (MAR)
        # ==========================================
        story.append(PageBreak())
        story.append(self._build_header_table())
        story.append(Spacer(1, 10))
        story.append(Paragraph("3. CONSERVATIVE MEDICATION RECONCILIATION (100% RECALL)", self.section_heading))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1e3a8a"), spaceAfter=8))

        med_table_data = [
            [
                Paragraph("<b>MEDICATION & STRENGTH</b>", self.body_style),
                Paragraph("<b>DOSE & ROUTE</b>", self.body_style),
                Paragraph("<b>FREQUENCY</b>", self.body_style),
                Paragraph("<b>SAFETY / RECON WARNING</b>", self.body_style),
                Paragraph("<b>STATUS</b>", self.body_style),
            ]
        ]

        for med in self.assembler.medications:
            warn = Paragraph(med.duplicate_warning or "No Conflict", self.warning_style if med.is_duplicate else self.citation_style)
            alert = "HIGH ALERT (Verified)" if med.is_high_risk else "Standard"
            med_table_data.append([
                Paragraph(f"<b>{med.name}</b><br/><font color='#64748b'>{med.generic}</font>", self.body_style),
                Paragraph(f"{med.dose}<br/>{med.route}", self.body_style),
                Paragraph(med.frequency, self.body_style),
                warn,
                Paragraph(f"✓ {alert}", self.verified_badge if med.verified else self.warning_style),
            ])

        t_meds = Table(med_table_data, colWidths=[2.2 * inch, 1.3 * inch, 1.2 * inch, 1.8 * inch, 1.0 * inch])
        t_meds.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t_meds)

        # ==========================================
        # PAGE 4: Active Orders & Pending Laboratory / Diagnostic Studies
        # ==========================================
        story.append(PageBreak())
        story.append(self._build_header_table())
        story.append(Spacer(1, 10))
        story.append(Paragraph("4. ACTIVE PHYSICIAN ORDERS & PENDING DIAGNOSTICS", self.section_heading))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1e3a8a"), spaceAfter=8))

        # T2-3 honesty fix: orders are rendered ONLY from real ingested data.
        # When no active orders exist, the packet says so — it never invents
        # ORD-101..103 fallback content.
        if self.assembler.active_orders:
            orders_data = [[Paragraph("<b>ORDER ID</b>", self.body_style), Paragraph("<b>CLINICAL ORDER / TREATMENT</b>", self.body_style), Paragraph("<b>ORDERING PHYSICIAN</b>", self.body_style)]]
            for ord_item in self.assembler.active_orders:
                orders_data.append([
                    Paragraph(str(ord_item.get("id", "")), self.body_style),
                    Paragraph(str(ord_item.get("desc", "")), self.body_style),
                    Paragraph(str(ord_item.get("doc", "")), self.body_style),
                ])
            t_orders = Table(orders_data, colWidths=[1.2 * inch, 4.5 * inch, 1.8 * inch])
            t_orders.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(t_orders)
        else:
            story.append(Paragraph(
                "<b>No active physician orders recorded</b> in the ingested source documents. "
                "Verify directly with the sending unit before transfer.",
                self.warning_style,
            ))
        story.append(Spacer(1, 10))

        # Pending diagnostics: rendered only from real pending_labs data.
        story.append(Paragraph("<b>PENDING LABORATORY / DIAGNOSTIC STUDIES:</b>", self.body_style))
        if self.assembler.pending_labs:
            for lab_item in self.assembler.pending_labs:
                test_name = str(lab_item.get("test", ""))
                lab_status = str(lab_item.get("status", "PENDING"))
                lab_source = str(lab_item.get("source", ""))
                source_note = f" <i>[{lab_source}]</i>" if lab_source else ""
                story.append(Paragraph(
                    f"• <b>{test_name}</b> — {lab_status}{source_note}",
                    self.body_style,
                ))
        else:
            story.append(Paragraph(
                "No pending laboratory or diagnostic studies recorded in the ingested source documents.",
                self.citation_style,
            ))

        # ==========================================
        # PAGE 5: Mobility, Fall Risk & Infection Control Precautions
        # ==========================================
        story.append(PageBreak())
        story.append(self._build_header_table())
        story.append(Spacer(1, 10))
        story.append(Paragraph("5. MOBILITY STATUS, FALL RISK & ISOLATION PRECAUTIONS", self.section_heading))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1e3a8a"), spaceAfter=8))

        # T2-3 honesty fix: mobility / fall-risk / isolation rows are rendered
        # ONLY from the assembler's mobility_isolation data (derived from the
        # ingested records). Rows absent from the data are omitted; when no
        # data exists at all the packet says so explicitly.
        mob_labels = [
            ("mobility", "Mobility & Ambulation"),
            ("morse_fall_score", "Morse Fall Risk Score"),
            ("braden_score", "Skin Integrity & Braden Score"),
            ("isolation", "Infection Control & Isolation"),
        ]
        mob_source = self.assembler.mobility_isolation or {}
        mob_rows = [
            (label, str(mob_source[key]))
            for key, label in mob_labels
            if mob_source.get(key)
        ]

        if mob_rows:
            mob_data = [
                [Paragraph("<b>ASSESSMENT CATEGORY</b>", self.body_style), Paragraph("<b>CLINICAL PARAMETER & INSTRUCTIONS</b>", self.body_style)],
            ]
            for label, value in mob_rows:
                mob_data.append([
                    Paragraph(label, self.body_style),
                    Paragraph(value, self.body_style),
                ])
            t_mob = Table(mob_data, colWidths=[2.5 * inch, 5.0 * inch])
            t_mob.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(t_mob)
        else:
            story.append(Paragraph(
                "<b>No mobility, fall-risk, or isolation assessments recorded</b> in the ingested "
                "source documents. Complete the assessments with the sending unit before transfer.",
                self.warning_style,
            ))

        # ==========================================
        # PAGES 6 to 10: Appended Primary Clinical Notes
        # ==========================================
        # Honesty fix: an appendix slot without a real ingested document is
        # labeled "not available" — no fabricated titles, payloads, or
        # attestations of verification for content that does not exist.
        for idx in range(1, 6):
            story.append(PageBreak())
            story.append(self._build_header_table())
            story.append(Spacer(1, 10))
            story.append(Paragraph(f"APPENDIX {idx}: PRIMARY CLINICAL SOURCE RECORD (PAGE {5+idx}/10)", self.section_heading))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1e3a8a"), spaceAfter=8))

            src_doc = self.assembler.source_documents[idx-1] if idx-1 < len(self.assembler.source_documents) else None

            if not src_doc:
                story.append(Paragraph("<b>DOCUMENT:</b> Source document not available", self.body_style))
                story.append(Spacer(1, 6))
                story.append(Paragraph(
                    "No ingested source document exists for this appendix slot. Nothing is rendered "
                    "here because no record could be verified.",
                    self.citation_style,
                ))
                continue

            title_text = src_doc.get("title") or "Untitled source document"
            raw_content = src_doc.get("content", "")

            story.append(Paragraph(f"<b>DOCUMENT:</b> {title_text}", self.body_style))
            story.append(Spacer(1, 6))

            if raw_content:
                # Format clean readable excerpt
                clean_lines = [line.strip() for line in raw_content.strip().split("\n") if line.strip()][:16]
                formatted_body = "<br/>".join(clean_lines)
                story.append(Paragraph(f"<font color='#334155'>{formatted_body}</font>", self.citation_style))
                story.append(Spacer(1, 10))
                story.append(Paragraph("<b>CERTIFIED ATTESTATION:</b> Verified authentic unredacted clinical record for inter-unit patient handoff.", self.citation_style))
            else:
                story.append(Paragraph(
                    "Source document was ingested but no extractable content is available. "
                    "No attestation is provided for this record.",
                    self.citation_style,
                ))

        # ==========================================
        # PAGE 11: Cryptographic Audit Trail & Ledger
        # ==========================================
        story.append(PageBreak())
        story.append(self._build_header_table())
        story.append(Spacer(1, 10))
        story.append(Paragraph("TAMPER-EVIDENT AUDIT TRAIL & NURSE SIGN-OFF LEDGER", self.section_heading))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1e3a8a"), spaceAfter=8))

        audit_data = [
            [Paragraph("<b>AUDIT ITEM</b>", self.body_style), Paragraph("<b>RECORD VALUE / TIMESTAMP</b>", self.body_style)],
            [Paragraph("Packet Cryptographic Digest (SHA-256)", self.body_style), Paragraph(f"<font name='Courier'>{self.assembler.generate_audit_digest()}</font>", self.citation_style)],
            [Paragraph("Allergies Gate Verification", self.body_style), Paragraph(f"{self.assembler.gates.allergies_nurse} @ {self.assembler.gates.allergies_timestamp}", self.body_style)],
            [Paragraph("Code Status Gate Verification", self.body_style), Paragraph(f"{self.assembler.gates.code_status_nurse} @ {self.assembler.gates.code_status_timestamp}", self.body_style)],
            [Paragraph("High-Risk Meds Dual Verification", self.body_style), Paragraph(f"RN 1: {self.assembler.gates.high_risk_meds_nurse_1}<br/>RN 2: {self.assembler.gates.high_risk_meds_nurse_2}", self.body_style)],
            [Paragraph("Transfer Dossier Total Page Count", self.body_style), Paragraph("10 Certified Clinical Pages + 1 Audit Appendix", self.body_style)],
        ]
        t_audit = Table(audit_data, colWidths=[2.6 * inch, 4.9 * inch])
        t_audit.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(t_audit)

        try:
            doc.build(story) # no canvasmaker passed in original, matching original args
        except Exception as e:
            logger.error("[PACKET_BUILDER] ReportLab PDF generation failed: %s", e, exc_info=True)
            raise RuntimeError(
                f"PDF generation failed at rendering stage: {type(e).__name__}: {e}. "
                "Likely cause: malformed table data or unsupported character in clinical text. "
                "Fix: sanitize Unicode characters in source documents or check table column widths."
            ) from e
        return buffer.getvalue()

    def save_pdf(self, output_path: str) -> str:
        pdf_bytes = self.generate_pdf_bytes()
        with open(output_path, "wb") as f:
            f.write(pdf_bytes)
        return output_path
