"""Inspect full_text of affected sections to identify artifact patterns."""
import sys, os
sys.path.insert(0, 'service')
from pdf_analyzer import analyze_pdf
from flow_mapper import build_flow_map

pdf_path = os.path.join('demo', [f for f in os.listdir('demo') if f.endswith('.pdf')][0])
doc = analyze_pdf(pdf_path)
fm = build_flow_map(doc)

targets = [
    "Abstract", "I. INTRODUCTION", "II. RELATED WORK",
    "D. DocPilot", "E. TracePilot", "F. GaugePilot",
    "G. Architectural Design Rationale",
    "D. Comparative Retrieval Analysis",
    "A. Architectural Design Decisions",
    "C. Current Limitations", "VII. CONCLUSION",
]

for frag in targets:
    sec = next((s for s in fm.sections if frag in s.title), None)
    if not sec:
        continue
    print(f"\n{'='*70}")
    print(f"=== {sec.title} ({sec.word_count} words) ===")
    print(f"{'='*70}")
    # Print full text, first 600 chars
    ft = sec.full_text
    print(ft[:600])
    print("...")
