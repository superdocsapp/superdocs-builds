"""Write a .pdf and a .docx copy of every document in a blind case, so the
whole pipeline can be driven with binary-format inputs. Content is the same
text rendered the way those formats really read (no markdown syntax);
only the container changes.

Usage: python tests/blind/write_pdf_copies.py <case_dir>
Writes: <case_dir>-pdf/ and <case_dir>-docx/ with the same layout.
"""
import sys
import textwrap
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

LINE_WIDTH_CHARS = 95
TOP_MARGIN = 60
LINE_HEIGHT = 13


def strip_markdown(text: str) -> str:
    """Render markdown the way a real PDF's text layer reads: no hash
    marks (headings become capitalized lines), no bold markers, no
    blockquote arrows."""
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            lines.append(line.lstrip("# ").upper())
        else:
            lines.append(line.replace("**", "").removeprefix("> "))
    return "\n".join(lines)


def write_pdf(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(target), pagesize=letter)
    pdf.setFont("Helvetica", 9)
    y = letter[1] - TOP_MARGIN
    for raw_line in strip_markdown(source.read_text(encoding="utf-8")).splitlines():
        pieces = textwrap.wrap(raw_line, LINE_WIDTH_CHARS) or [""]
        for piece in pieces:
            if y < TOP_MARGIN:
                pdf.showPage()
                pdf.setFont("Helvetica", 9)
                y = letter[1] - TOP_MARGIN
            pdf.drawString(50, y, piece)
            y -= LINE_HEIGHT
    pdf.save()


def write_docx(source: Path, target: Path) -> None:
    import docx

    target.parent.mkdir(parents=True, exist_ok=True)
    document = docx.Document()
    for line in strip_markdown(source.read_text(encoding="utf-8")).splitlines():
        if line.strip():
            document.add_paragraph(line)
    document.save(str(target))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tests/blind/write_pdf_copies.py <case_dir>")
    case = Path(sys.argv[1])
    count = 0
    for folder in ("notice", "petition"):
        for source in sorted((case / folder).glob("*.md")):
            write_pdf(source, case.parent / f"{case.name}-pdf" / folder / (source.stem + ".pdf"))
            write_docx(source, case.parent / f"{case.name}-docx" / folder / (source.stem + ".docx"))
            count += 1
    print(f"wrote {count} PDFs and {count} DOCX files under {case.parent / case.name}-pdf and -docx")


if __name__ == "__main__":
    main()
