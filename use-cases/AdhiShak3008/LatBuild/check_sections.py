"""Quick section check — run from LatBuild/ folder with your PDF in demo/."""
import sys, os
sys.path.insert(0, 'service')
from pdf_analyzer import analyze_pdf
from flow_mapper import build_flow_map

pdf_path = None
for f in sorted(os.listdir('demo')):
    if f.endswith('.pdf'):
        pdf_path = os.path.join('demo', f)
        break

if not pdf_path:
    print("No PDF found in demo/"); sys.exit(1)

print(f"Analyzing: {pdf_path}\n")
doc = analyze_pdf(pdf_path)
fm  = build_flow_map(doc)

print(f"Pages: {doc.page_count}  |  Total blocks: {len(doc.all_blocks)}")
print(f"Sections detected: {len(fm.sections)}\n")

print(f"{'#':<3} {'E':<2} {'Level':<6} {'Section title':<42} {'Pages':<10} {'Words'}")
print("-" * 80)
for i, s in enumerate(fm.sections):
    indent = "    " if s.level == 2 else ""
    editable = "Y" if s.is_editable else "-"
    pages_str = (str(s.start_page) if s.start_page == s.end_page
                 else f"{s.start_page}–{s.end_page}") if s.pages else "?"
    print(f"{i+1:<3} {editable:<2} L{s.level:<5} {indent}{s.title[:42-len(indent)]:<42} {pages_str:<10} {s.word_count}")

print()
print("=== TEXT PREVIEW PER SECTION (first 300 chars) ===")
for s in fm.sections:
    if s.level == 2:
        continue   # skip subsections for brevity
    print(f"\n--- {s.title} (L{s.level}, p{s.start_page}–{s.end_page}, {s.word_count} words) ---")
    print(s.full_text[:300].replace("\n", " "))
