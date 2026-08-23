"""Simulate the reflow for Conclusion with a sample rewrite."""
import sys, os
sys.path.insert(0, 'service')
from pdf_analyzer import analyze_pdf
from flow_mapper import build_flow_map
from reflow_engine import plan_reflow, estimate_lines_needed

pdf_path = os.path.join('demo', [f for f in os.listdir('demo') if f.endswith('.pdf')][0])
doc = analyze_pdf(pdf_path)
fm = build_flow_map(doc)

conc = next(s for s in fm.sections if "CONCLUSION" in s.title)
print(f"Conclusion: {conc.word_count} words, {len(conc.flow_regions)} regions")
for i, r in enumerate(conc.flow_regions):
    lines = r.capacity_lines(fm.grammar.body_line_height)
    print(f"  region {i}: p{r.page} col={r.column} h={r.bbox.height:.0f}pt "
          f"→ ~{lines} lines capacity")

# Estimate lines needed for original text
lines, height = estimate_lines_needed(
    conc.full_text, conc.flow_regions[0].column_width,
    fm.grammar.body_fontname, fm.grammar.body_fontsize, fm.grammar.body_line_height
)
total_capacity = sum(r.capacity_lines(fm.grammar.body_line_height) for r in conc.flow_regions)
print(f"\nOriginal text: {conc.word_count} words")
print(f"Estimated lines needed: {lines}")
print(f"Total capacity: {total_capacity} lines")

# Simulate with a sample rewrite
sample_rewrite = """This paper presented PilotMaster, a modular Retrieval Intelligence Platform that unifies document intelligence, retrieval observability, and experimental benchmarking within a shared retrieval engineering framework. By centralizing document ingestion, retrieval execution, evaluation, tracing, and benchmarking inside the reusable PilotCore framework, the platform enables multiple applications to operate over an identical retrieval pipeline while avoiding duplicated implementation.

The proposed platform demonstrates that retrieval engineering extends beyond response generation alone and requires comprehensive support for experimentation, evaluation, and diagnostic analysis. Through the integration of DocPilot, TracePilot, and GaugePilot, PilotMaster provides an end-to-end environment for developing, analyzing, benchmarking, and optimizing Retrieval-Augmented Generation (RAG) systems."""

result = plan_reflow(conc, sample_rewrite, fm)
print(f"\nReflow result:")
print(f"  patches: {len(result.section_patches)}")
print(f"  delta_lines: {result.delta_lines}")
print(f"  can_apply: {result.can_apply}")
for i, p in enumerate(result.section_patches):
    print(f"  patch {i}: op={p.operation} region=p{p.region.page} col={p.region.column} "
          f"text_len={len(p.text_segment)} words={len(p.text_segment.split())}")
