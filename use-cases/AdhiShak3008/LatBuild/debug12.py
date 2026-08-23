"""Diagnose: heading boundary, F. GaugePilot missing, content availability."""
import sys, os
sys.path.insert(0, 'service')
from pdf_analyzer import analyze_pdf
from flow_mapper import build_flow_map

pdf_path = [os.path.join('demo', f) for f in os.listdir('demo') if f.endswith('.pdf')][0]
doc = analyze_pdf(pdf_path)
fm = build_flow_map(doc)

print("=== ISSUE 1: D. DocPilot heading boundary ===")
d_sec = next((s for s in fm.sections if "DocPilot" in s.title), None)
if d_sec:
    print(f"  Title: '{d_sec.title}'")
    print(f"  Heading block text: '{d_sec.heading_block.text[:100] if d_sec.heading_block else 'None'}'")
    print(f"  Word count: {d_sec.word_count}")
    print(f"  Blocks: {len(d_sec.content_blocks)}")
    if d_sec.content_blocks:
        print(f"  First block: '{d_sec.content_blocks[0].text[:100]}'")
else:
    print("  NOT FOUND")

print("\n=== ISSUE 2: F. GaugePilot missing ===")
# Check all heading blocks on pages 4-5 for 'GaugePilot' or 'F.'
print("  All blocks on p4-5 that contain 'GaugePilot' or start with 'F.':")
for b in doc.all_blocks:
    if b.page in (4, 5):
        if 'GaugePilot' in b.text or 'Gauge' in b.text or b.text.strip().startswith('F.'):
            flag = "[H]" if b.is_heading else "   "
            print(f"    {flag} p{b.page} col={b.column} '{b.text[:80]}'")

# Check if F. pattern exists anywhere in raw text
import pdfplumber
with pdfplumber.open(pdf_path) as pdf:
    for pn in [4, 5]:
        page = pdf.pages[pn-1]
        words = page.extract_words(extra_attrs=['fontname','size'], use_text_flow=False)
        f_words = [w for w in words if w['text'].strip() in ('F.', 'GaugePilot')]
        if f_words:
            print(f"  Raw words on page {pn} matching 'F.' or 'GaugePilot':")
            for w in f_words:
                print(f"    x0={w['x0']:.1f} top={w['top']:.1f} size={w.get('size',0):.1f} '{w['text']}'")

print("\n=== ISSUE 3: Content availability ===")
test_sections = ["I. INTRODUCTION", "II. RELATED WORK", "III. SYSTEM ARCHITECTURE"]
for title in test_sections:
    sec = next((s for s in fm.sections if title in s.title), None)
    if sec:
        ft = sec.full_text
        print(f"  {sec.title}:")
        print(f"    word_count={sec.word_count}, len(full_text)={len(ft)}, blocks={len(sec.content_blocks)}")
        print(f"    Preview: '{ft[:150]}'")
    else:
        print(f"  {title}: NOT FOUND")

# Check subsections of III
print("\n  Subsections of III:")
iii = next((s for s in fm.sections if "III." in s.title), None)
if iii:
    children = fm.children_of(iii)
    for c in children:
        ft = c.full_text
        print(f"    {c.title}: words={c.word_count}, len={len(ft)}, blocks={len(c.content_blocks)}")
        print(f"      Preview: '{ft[:100]}'")
