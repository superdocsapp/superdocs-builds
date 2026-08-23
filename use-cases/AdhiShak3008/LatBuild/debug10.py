"""Show all words near 'VI.' on page 10."""
import sys, os
sys.path.insert(0, 'service')
import pdfplumber

pdf_path = [os.path.join('demo', f) for f in os.listdir('demo') if f.endswith('.pdf')][0]
with pdfplumber.open(pdf_path) as pdf:
    page = pdf.pages[9]  # page 10
    words = page.extract_words(extra_attrs=['fontname','size'], use_text_flow=False)
    
    # Show all words from top=420 to top=620 on right column
    print("Page 10, right column (x0>300), top 420-620:")
    zone = [w for w in words if w['x0'] > 300 and 420 < w['top'] < 620]
    for w in sorted(zone, key=lambda w: (w['top'], w['x0'])):
        print(f"  x0={w['x0']:6.1f} top={w['top']:6.1f} bot={w['bottom']:6.1f} size={float(w.get('size',0)):.1f}  '{w['text']}'")
