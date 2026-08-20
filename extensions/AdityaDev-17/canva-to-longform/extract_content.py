"""
extract_content.py — extracts copy (text) from the PDF and a color
palette from the PNG. This is the "reads the design's copy and
visual system" step from the card, made concrete.

Real bug found and fixed: Canva's PDF export places each character
individually rather than as flowing text runs, so pypdf's gap-based
extraction inserts a space between every letter ("A u g u s t" instead
of "August"). fix_char_spaced_text() detects this pattern per line and
collapses it - single spaces (artificial character gaps) are removed,
while double spaces (genuine word boundaries, which Canva renders as
a wider gap) are preserved as real word breaks.
"""
import re
from pathlib import Path

from pypdf import PdfReader
from PIL import Image

DESIGN_ID = "DAHSiXKMgD4"
ASSET_DIR = Path("design_assets") / DESIGN_ID


def fix_char_spaced_text(text: str) -> str:
    """Collapses per-character spacing artifacts from Canva's PDF
    export back into real words, while preserving genuine word gaps
    (rendered as double spaces in the source)."""
    lines = text.split("\n")
    fixed_lines = []
    for line in lines:
        if re.search(r"(?:\b\w\s){3,}\w\b", line):
            line = line.replace("  ", "\x00")  # protect real word gaps
            line = line.replace(" ", "")        # remove char-level gaps
            line = line.replace("\x00", " ")    # restore real word gaps
        fixed_lines.append(line)
    return "\n".join(fixed_lines)


def extract_text(pdf_path: Path) -> str:
    reader = PdfReader(pdf_path)
    raw = "\n".join(page.extract_text() or "" for page in reader.pages)
    return fix_char_spaced_text(raw)


def extract_palette(image_path: Path, num_colors: int = 5) -> list[str]:
    img = Image.open(image_path).convert("RGB")
    img_small = img.resize((150, 150))
    quantized = img_small.quantize(colors=num_colors, method=Image.MEDIANCUT)
    palette = quantized.getpalette()
    color_counts = quantized.getcolors()
    color_counts.sort(reverse=True, key=lambda x: x[0])

    hex_colors = []
    for count, idx in color_counts[:num_colors]:
        r, g, b = palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2]
        hex_colors.append(f"#{r:02x}{g:02x}{b:02x}")
    return hex_colors


if __name__ == "__main__":
    pdf_path = ASSET_DIR / "page_1.pdf"
    png_path = ASSET_DIR / "page_1.png"

    print("=== Extracted text (the copy) ===")
    text = extract_text(pdf_path)
    print(text)
    print(f"\n({len(text)} characters)")

    print("\n=== Extracted color palette (the visual system) ===")
    colors = extract_palette(png_path)
    for c in colors:
        print(f"  {c}")