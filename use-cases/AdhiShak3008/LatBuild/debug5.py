"""Show blocks on page 1 and 2 to diagnose merged headings."""
import sys, os
sys.path.insert(0, 'service')
from pdf_analyzer import analyze_pdf, _ROMAN_HEADING_RE, _ALPHA_HEADING_RE

pdf_path = [os.path.join('demo', f) for f in os.listdir('demo') if f.endswith('.pdf')][0]
doc = analyze_pdf(pdf_path)

for page_num in [1, 2, 3, 8]:
    blocks = [b for b in doc.all_blocks if b.page == page_num]
    print(f"\n=== PAGE {page_num}: {len(blocks)} blocks ===")
    for b in blocks:
        flag = "[H]" if b.is_heading else "   "
        preview = b.text[:70].replace('\n', ' ')
        print(f"  {flag} col={b.column} y0={b.bbox.y0:6.1f} fs={b.fontsize:.1f}  '{preview}'")
