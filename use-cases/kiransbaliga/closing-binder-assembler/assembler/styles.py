"""Styling, legal typography, and color palette for PDF closing binder generation."""

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch

# Corporate M&A Legal Palette
NAVY_PRIMARY = colors.HexColor("#0B1B3D")       # Deep Deal Navy
SLATE_SECONDARY = colors.HexColor("#2C3E50")    # Slate Charcoal
GOLD_ACCENT = colors.HexColor("#C5A059")        # Legal Gold Accent
BORDER_GREY = colors.HexColor("#E2E8F0")        # Subtle Border
BG_LIGHT = colors.HexColor("#F8FAFC")           # Off-white / Ivory
TEXT_DARK = colors.HexColor("#1E293B")          # Charcoal Body Text
TEXT_MUTED = colors.HexColor("#64748B")         # Muted Slate
SUCCESS_GREEN = colors.HexColor("#166534")      # Executed Green
WARNING_AMBER = colors.HexColor("#B45309")      # Partial Amber
DANGER_RED = colors.HexColor("#991B1B")         # Unsigned / Missing Red


def get_legal_binder_styles():
    """Generates custom ReportLab styles tailored for M&A closing binders."""
    base_styles = getSampleStyleSheet()

    # Cover Page Styles
    cover_firm = ParagraphStyle(
        "CoverFirm",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=GOLD_ACCENT,
        alignment=1,  # Center
        spaceAfter=15,
    )

    cover_title = ParagraphStyle(
        "CoverTitle",
        parent=base_styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=26,
        leading=32,
        textColor=NAVY_PRIMARY,
        alignment=1,
        spaceAfter=12,
    )

    cover_subtitle = ParagraphStyle(
        "CoverSubtitle",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=13,
        leading=18,
        textColor=SLATE_SECONDARY,
        alignment=1,
        spaceAfter=25,
    )

    cover_meta = ParagraphStyle(
        "CoverMeta",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=15,
        textColor=TEXT_DARK,
        alignment=1,
    )

    # Table of Contents Styles
    toc_heading = ParagraphStyle(
        "TOCHeading",
        parent=base_styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=NAVY_PRIMARY,
        spaceAfter=15,
    )

    toc_category = ParagraphStyle(
        "TOCCategory",
        parent=base_styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=SLATE_SECONDARY,
        spaceBefore=12,
        spaceAfter=6,
    )

    toc_item = ParagraphStyle(
        "TOCItem",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=TEXT_DARK,
    )

    # Tab Divider Styles
    tab_number_large = ParagraphStyle(
        "TabNumberLarge",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=36,
        leading=42,
        textColor=GOLD_ACCENT,
        alignment=1,
        spaceAfter=10,
    )

    tab_title = ParagraphStyle(
        "TabTitle",
        parent=base_styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=26,
        textColor=NAVY_PRIMARY,
        alignment=1,
        spaceAfter=15,
    )

    tab_category_badge = ParagraphStyle(
        "TabCategoryBadge",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=SLATE_SECONDARY,
        alignment=1,
        spaceAfter=20,
    )

    body_legal = ParagraphStyle(
        "BodyLegal",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=TEXT_DARK,
    )

    return {
        "cover_firm": cover_firm,
        "cover_title": cover_title,
        "cover_subtitle": cover_subtitle,
        "cover_meta": cover_meta,
        "toc_heading": toc_heading,
        "toc_category": toc_category,
        "toc_item": toc_item,
        "tab_number_large": tab_number_large,
        "tab_title": tab_title,
        "tab_category_badge": tab_category_badge,
        "body_legal": body_legal,
    }
