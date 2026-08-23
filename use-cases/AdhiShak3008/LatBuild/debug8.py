"""Diagnose pages 4, 5, 10, 11, 12 in detail."""
import sys, os
sys.path.insert(0, 'service')
from pdf_analyzer import analyze_pdf

pdf_path = [os.path.join('demo', f) for f in os.listdir('demo') if f.endswith('.pdf')][0]
doc = analyze_pdf(pdf_path)

for page_num in [4, 5, 10, 11, 12]:
    blocks = [b for b in doc.all_blocks if b.page == page_num]
    print(f"\n=== PAGE {page_num}: {len(blocks)} blocks ===")
    for b in blocks:
        flag = "[H]" if b.is_heading else "   "
        print(f"  {flag} col={b.column} y0={b.bbox.y0:6.1f} fs={b.fontsize:.1f}  '{b.text[:90]}'")
