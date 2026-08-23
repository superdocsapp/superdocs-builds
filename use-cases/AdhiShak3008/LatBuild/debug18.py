"""Trace exactly what happens to Abstract block through the pipeline."""
import sys, os
sys.path.insert(0, 'service')
import fitz
import pdfplumber

pdf_path = os.path.join('demo', [f for f in os.listdir('demo') if f.endswith('.pdf')][0])

# 1. What does pdfplumber give us for the Abstract heading line?
print("=== pdfplumber words near y=195 on page 1 ===")
with pdfplumber.open(pdf_path) as pdf:
    page = pdf.pages[0]
    words = page.extract_words(extra_attrs=['fontname','size'], use_text_flow=False)
    abstract_words = [w for w in words if 190 < w['top'] < 210]
    for w in sorted(abstract_words, key=lambda w: w['x0']):
        print(f"  x0={w['x0']:.1f} top={w['top']:.1f} x1={w['x1']:.1f} bot={w['bottom']:.1f} '{w['text']}'")

# 2. What bbox does the paragraph grouper assign?
# The pdfplumber paragraph for this block would span y0=195 to y1=some_bottom
# Let's check what pymupdf extracts from that same region
doc = fitz.open(pdf_path)
page = doc[0]
print("\n=== pymupdf extraction from abstract heading bbox ===")
# Try a narrow bbox (just the heading line)
rect_narrow = fitz.Rect(49, 194, 300, 206)
text_narrow = page.get_text("text", clip=rect_narrow).strip()
print(f"Narrow bbox (194-206): '{text_narrow}'")

# Try a wider bbox  
rect_wide = fitz.Rect(49, 194, 300, 480)
text_wide = page.get_text("text", clip=rect_wide).strip()
print(f"Wide bbox (194-480): '{text_wide[:200]}'")
doc.close()
