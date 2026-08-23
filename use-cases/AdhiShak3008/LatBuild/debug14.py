"""Diagnose column contamination in affected sections."""
import sys, os
sys.path.insert(0, 'service')
from pdf_analyzer import analyze_pdf, PDFAnalyzer
from flow_mapper import build_flow_map
import pdfplumber

pdf_path = os.path.join('demo', [f for f in os.listdir('demo') if f.endswith('.pdf')][0])
doc = analyze_pdf(pdf_path)
fm = build_flow_map(doc)

# Inspect affected sections
affected = ["D. DocPilot", "F. GaugePilot", "E. TracePilot", 
            "A. Architectural Design Decisions", "D. Comparative Retrieval Analysis"]

for title_fragment in affected:
    sec = next((s for s in fm.sections if title_fragment in s.title), None)
    if not sec:
        print(f"\n=== {title_fragment}: NOT FOUND ===")
        continue
    print(f"\n=== {sec.title} (p{sec.start_page}-{sec.end_page}, {sec.word_count} words, {len(sec.content_blocks)} blocks) ===")
    for i, b in enumerate(sec.content_blocks):
        print(f"  Block {i}: p{b.page} col={b.column} y0={b.bbox.y0:.1f}-{b.bbox.y1:.1f} "
              f"x0={b.bbox.x0:.1f}-{b.bbox.x1:.1f}")
        print(f"    Text[0:120]: '{b.text[:120]}'")

# Now inspect the split_x used per page for pages 4, 9, 10
print("\n\n=== SPLIT_X PER PAGE ===")
for page_layout in doc.pages:
    if page_layout.page_number in (4, 5, 9, 10, 11, 12):
        print(f"  Page {page_layout.page_number}: split_x={page_layout.split_x:.1f}, "
              f"cols={len(page_layout.columns)}, blocks={len(page_layout.text_blocks)}")
        for c in page_layout.columns:
            print(f"    col {c.index}: x0={c.x0:.1f} x1={c.x1:.1f}")

# Check page 4 specifically - where D. DocPilot lives
print("\n\n=== PAGE 4 DETAILED BLOCKS ===")
p4_blocks = [b for b in doc.all_blocks if b.page == 4]
for b in p4_blocks:
    flag = "[H]" if b.is_heading else "   "
    print(f"  {flag} col={b.column} x0={b.bbox.x0:.1f}-{b.bbox.x1:.1f} y0={b.bbox.y0:.1f} "
          f"'{b.text[:80]}'")
