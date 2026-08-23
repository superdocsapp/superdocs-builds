"""Find VI. DISCUSSION in the raw PDF."""
import sys, os
sys.path.insert(0, 'service')
import pdfplumber, re

pdf_path = [os.path.join('demo', f) for f in os.listdir('demo') if f.endswith('.pdf')][0]
with pdfplumber.open(pdf_path) as pdf:
    for page_obj in pdf.pages[9:12]:  # pages 10-12
        words = page_obj.extract_words(extra_attrs=['fontname','size'], use_text_flow=False)
        print(f"\n=== PAGE {page_obj.page_number} ===")
        # Print lines that contain 'VI' or 'DISCUSSION'
        for w in sorted(words, key=lambda w: (w['top'], w['x0'])):
            if any(x in w['text'].upper() for x in ['VI.', 'DISCUSSION', 'DISCUSS']):
                print(f"  x0={w['x0']:6.1f} top={w['top']:6.1f} size={float(w.get('size',0)):.1f}  '{w['text']}'")
        
        # Also show all lines on page 10 col 1 to find where VI is
        if page_obj.page_number == 10:
            print("\n  All words on p10 col1 (x0 > 300), sorted by top:")
            right_words = [w for w in words if w['x0'] > 300]
            for w in sorted(right_words, key=lambda w: w['top'])[:40]:
                print(f"  x0={w['x0']:6.1f} top={w['top']:6.1f} size={float(w.get('size',0)):.1f}  '{w['text']}'")
