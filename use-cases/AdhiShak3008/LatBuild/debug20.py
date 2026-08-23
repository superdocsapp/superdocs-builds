"""Verify pymupdf coordinate system on page 12."""
import sys, os
sys.path.insert(0, 'service')
import fitz

pdf_path = os.path.join('demo', [f for f in os.listdir('demo') if f.endswith('.pdf')][0])
doc = fitz.open(pdf_path)
page = doc[11]  # page 12

print(f"Page rect: {page.rect}")
print(f"Page height: {page.rect.height}")

# What text is at y=494-719 in pymupdf coordinates?
rect_pdfplumber = fitz.Rect(49, 494, 300, 719)
text = page.get_text("text", clip=rect_pdfplumber).strip()
print(f"\nText at y=494-719 (pdfplumber coords): '{text[:200]}'")

# What text is at the converted coordinates?
ph = page.rect.height
rect_converted = fitz.Rect(49, ph-719, 300, ph-494)
text2 = page.get_text("text", clip=rect_converted).strip()
print(f"\nText at y={ph-719:.0f}-{ph-494:.0f} (converted): '{text2[:200]}'")

# Where is "This paper presented" (Conclusion body)?
print("\nSearching for 'This paper presented' location:")
hits = page.search_for("This paper presented")
for h in hits:
    print(f"  Found at: {h}")

doc.close()
