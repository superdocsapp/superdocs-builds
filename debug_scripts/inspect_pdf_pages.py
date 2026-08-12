import fitz
import sys

pdf_path = sys.argv[1] if len(sys.argv) > 1 else "../output/final_review_package.pdf"
doc = fitz.open(pdf_path)

print(f"Total pages: {len(doc)}")
print()
for page_num in range(len(doc)):
    page = doc[page_num]
    text = page.get_text().strip()
    images = page.get_images()
    print(f"=== Page {page_num + 1} ({len(images)} image(s) on this page) ===")
    print(text[:400] if text else "(no extractable text)")
    print()
