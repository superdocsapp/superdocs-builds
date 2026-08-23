"""Inspect page 12 blocks and section flow regions for Conclusion and Availability."""
import sys, os
sys.path.insert(0, 'service')
from pdf_analyzer import analyze_pdf
from flow_mapper import build_flow_map

pdf_path = os.path.join('demo', [f for f in os.listdir('demo') if f.endswith('.pdf')][0])
doc = analyze_pdf(pdf_path)
fm = build_flow_map(doc)

print("=== Page 12 ALL blocks ===")
for b in doc.all_blocks:
    if b.page == 12:
        flag = "[H]" if b.is_heading else "   "
        print(f"  {flag} col={b.column} x0={b.bbox.x0:.0f}-{b.bbox.x1:.0f} "
              f"y0={b.bbox.y0:.0f}-{b.bbox.y1:.0f} '{b.text[:60]}'")

print("\n=== VII. CONCLUSION flow regions ===")
conc = next((s for s in fm.sections if "CONCLUSION" in s.title), None)
if conc:
    print(f"  title: {conc.title}")
    print(f"  pages: {conc.pages}, words: {conc.word_count}")
    print(f"  content blocks: {len(conc.content_blocks)}")
    for i, b in enumerate(conc.content_blocks):
        print(f"    block {i}: p{b.page} col={b.column} "
              f"y0={b.bbox.y0:.0f}-{b.bbox.y1:.0f} x0={b.bbox.x0:.0f}-{b.bbox.x1:.0f}")
    print(f"  flow regions: {len(conc.flow_regions)}")
    for i, r in enumerate(conc.flow_regions):
        print(f"    region {i}: p{r.page} col={r.column} "
              f"y0={r.bbox.y0:.0f}-{r.bbox.y1:.0f} x0={r.bbox.x0:.0f}-{r.bbox.x1:.0f} "
              f"h={r.bbox.height:.0f}")

print("\n=== VIII. PROJECT AVAILABILITY flow regions ===")
avail = next((s for s in fm.sections if "PROJECT" in s.title or "AVAIL" in s.title.upper()), None)
if avail:
    print(f"  title: {avail.title}")
    print(f"  pages: {avail.pages}, words: {avail.word_count}")
    for i, b in enumerate(avail.content_blocks):
        print(f"    block {i}: p{b.page} col={b.column} "
              f"y0={b.bbox.y0:.0f}-{b.bbox.y1:.0f} x0={b.bbox.x0:.0f}-{b.bbox.x1:.0f}")
    for i, r in enumerate(avail.flow_regions):
        print(f"    region {i}: p{r.page} col={r.column} "
              f"y0={r.bbox.y0:.0f}-{r.bbox.y1:.0f} x0={r.bbox.x0:.0f}-{r.bbox.x1:.0f} "
              f"h={r.bbox.height:.0f}")

print("\n=== Page dimensions ===")
print(f"  grammar: {doc.grammar.page_width:.0f} x {doc.grammar.page_height:.0f}")
print(f"  split_x: {doc.grammar.split_x:.0f}")
