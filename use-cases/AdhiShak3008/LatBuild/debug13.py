import sys, os
sys.path.insert(0, 'service')
from pdf_analyzer import analyze_pdf
from flow_mapper import FlowMapper, _clean_title
pdf = os.path.join('demo', [f for f in os.listdir('demo') if f.endswith('.pdf')][0])
doc = analyze_pdf(pdf)
for b in doc.all_blocks:
    if any(x in b.text for x in ['Lewis', 'Nogueira', 'Cormack']):
        print(f"  p{b.page} col={b.column} hdg={b.is_heading} text='{b.text[:80]}'")
        if b.is_heading:
            cleaned = _clean_title(b.text)
            print(f"    cleaned title='{cleaned}'")
            mapper = FlowMapper()
            print(f"    is_bibliographic='{mapper._is_bibliographic(b.text)}'")
