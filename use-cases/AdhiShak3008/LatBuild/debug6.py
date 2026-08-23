"""Find all heading blocks across all pages."""
import sys, os
sys.path.insert(0, 'service')
from pdf_analyzer import analyze_pdf

pdf_path = [os.path.join('demo', f) for f in os.listdir('demo') if f.endswith('.pdf')][0]
doc = analyze_pdf(pdf_path)
print("All heading blocks:")
for b in doc.all_blocks:
    if b.is_heading:
        print(f"  p{b.page} col={b.column} y0={b.bbox.y0:6.1f}  '{b.text[:80]}'")
