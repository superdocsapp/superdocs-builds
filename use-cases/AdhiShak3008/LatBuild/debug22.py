"""Check Abstract region dimensions."""
import sys, os
sys.path.insert(0, 'service')
from pdf_analyzer import analyze_pdf
from flow_mapper import build_flow_map
from reflow_engine import estimate_lines_needed
import fitz

pdf_path = os.path.join('demo', [f for f in os.listdir('demo') if f.endswith('.pdf')][0])
doc = analyze_pdf(pdf_path)
fm = build_flow_map(doc)

abstract = next((s for s in fm.sections if "Abstract" in s.title and s.is_editable), None)
print(f"Abstract: {abstract.word_count} words, {len(abstract.flow_regions)} regions")
for i, r in enumerate(abstract.flow_regions):
    print(f"  region {i}: p{r.page} col={r.column} "
          f"y0={r.bbox.y0:.1f} y1={r.bbox.y1:.1f} h={r.bbox.height:.1f}pt "
          f"w={r.column_width:.1f}pt")
    lines_cap = r.capacity_lines(fm.grammar.body_line_height)
    print(f"  capacity: ~{lines_cap} lines @ {fm.grammar.body_line_height:.1f}pt line height")

# Estimate lines for the original text
lines, height = estimate_lines_needed(
    abstract.full_text, abstract.flow_regions[0].column_width,
    fm.grammar.body_fontname, fm.grammar.body_fontsize, fm.grammar.body_line_height
)
print(f"\nOriginal text: {abstract.word_count} words → {lines} lines estimated, {height:.1f}pt")
print(f"Region height: {abstract.flow_regions[0].bbox.height:.1f}pt")
print(f"Fits: {height <= abstract.flow_regions[0].bbox.height}")

# Test actual insert_textbox
fdoc = fitz.open(pdf_path)
page = fdoc[0]
r = abstract.flow_regions[0]
rect = fitz.Rect(r.bbox.x0, r.bbox.y0, r.bbox.x1, r.bbox.y1)
print(f"\nfitz.Rect: {rect}")
result = page.insert_textbox(rect, abstract.full_text,
                              fontname="Times-Roman", fontsize=fm.grammar.body_fontsize)
print(f"insert_textbox result: {result} (negative = overflow)")
fdoc.close()
