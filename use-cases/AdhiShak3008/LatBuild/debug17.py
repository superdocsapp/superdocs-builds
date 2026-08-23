"""Diagnose: why Abstract is missing, and show what page 1 blocks look like now."""
import sys, os
sys.path.insert(0, 'service')
from pdf_analyzer import analyze_pdf
from flow_mapper import build_flow_map

pdf_path = os.path.join('demo', [f for f in os.listdir('demo') if f.endswith('.pdf')][0])
doc = analyze_pdf(pdf_path)
fm = build_flow_map(doc)

print("All sections:")
for s in fm.sections:
    print(f"  {'[H]' if s.is_editable else '   '} {s.title[:50]} - {s.word_count}w")

print("\nPage 1 blocks after pymupdf replacement:")
for b in doc.all_blocks:
    if b.page == 1:
        flag = "[H]" if b.is_heading else "   "
        print(f"  {flag} col={b.column} y0={b.bbox.y0:.0f} '{b.text[:80]}'")
