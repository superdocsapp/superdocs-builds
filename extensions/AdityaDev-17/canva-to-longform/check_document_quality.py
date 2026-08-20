"""
check_document_quality.py — runs the quality gate against the real
consistency_test_output.html we already generated, to confirm it
correctly flags the real duplicate-section bug found earlier - not
just synthetic test data.
"""
from pathlib import Path

from document_quality import run_quality_report
from extract_content import extract_palette

DESIGN_ID = "DAHSiXKMgD4"
colors = extract_palette(Path("design_assets") / DESIGN_ID / "page_1.png")
primary = colors[0]

html = Path("consistency_test_output.html").read_text(encoding="utf-8")
passed = run_quality_report(html, primary)

print(f"\nGate result: {'PASS' if passed else 'FAIL - do not export/commit without review'}")