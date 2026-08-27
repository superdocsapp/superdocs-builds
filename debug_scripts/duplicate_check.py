import fitz

doc = fitz.open("../output/final_review_package.pdf")
full_text = "".join(page.get_text() for page in doc)

print(f"Total pages: {len(doc)}")
print(f"Total extracted text length: {len(full_text)} chars")
print()

headings = [
    "Search Strategy Appendix",
    "Risk of Bias Summary",
    "Table 1. Characteristics",
    "Discussion",
]
for heading in headings:
    count = full_text.count(heading)
    flag = " <-- DUPLICATE" if count > 1 else ""
    print(f"{heading!r}: appears {count} time(s){flag}")

print()
print("--- Full text, unretruncated ---")
print(full_text)
