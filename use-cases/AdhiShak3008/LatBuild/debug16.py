"""Compare pdfplumber vs pymupdf text extraction on page 12 (Conclusion)."""
import sys, os
sys.path.insert(0, 'service')
import pdfplumber
import fitz  # pymupdf

pdf_path = os.path.join('demo', [f for f in os.listdir('demo') if f.endswith('.pdf')][0])

# pymupdf extraction
doc = fitz.open(pdf_path)
page = doc[11]  # page 12 (0-indexed)
# Get text with pymupdf's space inference
text_pymupdf = page.get_text("text")
print("=== PYMUPDF page 12 (first 800 chars) ===")
print(text_pymupdf[:800])
doc.close()

print("\n\n=== PDFPLUMBER page 12 (first 800 chars, words joined) ===")
with pdfplumber.open(pdf_path) as pdf:
    page = pdf.pages[11]
    words = page.extract_words(extra_attrs=['fontname','size'], use_text_flow=False)
    # Sort by (top, x0) and join
    sorted_w = sorted(words, key=lambda w: (w['top'], w['x0']))
    text_plumber = " ".join(w['text'] for w in sorted_w)
    print(text_plumber[:800])
