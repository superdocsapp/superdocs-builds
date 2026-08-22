import io
import textwrap
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors


def render_markdown_to_pdf(title: str, markdown_content: str) -> bytes:
    """
    Renders dynamic markdown text into a styled, professional multi-page PDF document.
    Handles headers, bullet points, horizontal rules, and wrapped body text dynamically.
    """
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Margins and layout coordinates
    margin_left = 50
    margin_right = 50
    usable_width = width - margin_left - margin_right
    y_position = height - 50
    line_height = 14
    page_num = 1

    def draw_footer():
        p.setFont("Helvetica", 8)
        p.setFillColor(colors.HexColor("#64748b"))
        p.drawString(margin_left, 30, f"SuperDocs Compliance Engine · ESG Attestation Document")
        p.drawRightString(width - margin_right, 30, f"Page {page_num}")
        p.setStrokeColor(colors.HexColor("#e2e8f0"))
        p.setLineWidth(0.5)
        p.line(margin_left, 42, width - margin_right, 42)

    lines = markdown_content.splitlines()

    for line in lines:
        stripped = line.strip()

        # Check page boundary
        if y_position < 60:
            draw_footer()
            p.showPage()
            page_num += 1
            y_position = height - 50

        # Horizontal Rule
        if stripped in ["---", "___", "***"]:
            p.setStrokeColor(colors.HexColor("#cbd5e1"))
            p.setLineWidth(0.75)
            p.line(margin_left, y_position - 3, width - margin_right, y_position - 3)
            y_position -= 15
            continue

        # Header 1 (# Title)
        if stripped.startswith("# "):
            p.setFont("Helvetica-Bold", 14)
            p.setFillColor(colors.HexColor("#0f172a"))
            text = stripped[2:].strip()
            p.drawString(margin_left, y_position, text)
            y_position -= 20
            continue

        # Header 2 (## Subtitle)
        if stripped.startswith("## "):
            p.setFont("Helvetica-Bold", 12)
            p.setFillColor(colors.HexColor("#1e293b"))
            text = stripped[3:].strip()
            p.drawString(margin_left, y_position, text)
            y_position -= 16
            continue

        # Header 3 (### Sub-section)
        if stripped.startswith("### "):
            p.setFont("Helvetica-Bold", 10)
            p.setFillColor(colors.HexColor("#334155"))
            text = stripped[4:].strip()
            p.drawString(margin_left, y_position, text)
            y_position -= 14
            continue

        # Bullet point or list item
        if stripped.startswith("- ") or stripped.startswith("* "):
            p.setFont("Helvetica", 9)
            p.setFillColor(colors.HexColor("#334155"))
            bullet_text = stripped[2:].strip()
            wrapped_chunks = textwrap.wrap(bullet_text, width=85)
            for i, chunk in enumerate(wrapped_chunks):
                if y_position < 60:
                    draw_footer()
                    p.showPage()
                    page_num += 1
                    y_position = height - 50
                if i == 0:
                    p.drawString(margin_left + 5, y_position, "•")
                    p.drawString(margin_left + 15, y_position, chunk)
                else:
                    p.drawString(margin_left + 15, y_position, chunk)
                y_position -= line_height
            continue

        # Empty line
        if not stripped:
            y_position -= 8
            continue

        # Standard paragraph line
        p.setFont("Helvetica", 9)
        p.setFillColor(colors.HexColor("#334155"))
        # Strip simple markdown bold asterisks for clean PDF display
        clean_text = stripped.replace("**", "").replace("`", "")
        wrapped_chunks = textwrap.wrap(clean_text, width=90)
        for chunk in wrapped_chunks:
            if y_position < 60:
                draw_footer()
                p.showPage()
                page_num += 1
                y_position = height - 50
            p.drawString(margin_left, y_position, chunk)
            y_position -= line_height

    # Final page footer
    draw_footer()
    p.showPage()
    p.save()

    buffer.seek(0)
    return buffer.getvalue()
