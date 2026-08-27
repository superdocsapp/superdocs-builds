"""Reproduces the exact v5 pipeline order up to and including risk-of-bias,
to see whether fabrication reproduces reliably at this specific chain
depth/content combination, or whether it's intermittent."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flow_diagram import load_counts, render_flow_diagram
from build_tables import (
    build_evidence_table_html,
    build_search_strategy_html,
    build_risk_of_bias_html,
)
from insert_content import insert_html_via_review
from superdocs_client import (
    upload_document,
    new_session_id,
    resolve_any_pending_approval,
)

SESSION_ID = new_session_id("full-chain-test")
resolve_any_pending_approval(SESSION_ID, approve=False)

counts = load_counts("../sample_data/screening_counts.json")
diagram_path = render_flow_diagram(counts, "../output/flow_diagram_chaintest.png")

upload_result = upload_document("../sample_data/draft_manuscript.html", SESSION_ID)
current_html = upload_result["html"]

current_html = insert_html_via_review(
    SESSION_ID,
    current_html,
    instruction="Insert the attached flow diagram image immediately after the Methods section, with a caption identifying it as the study flow diagram.",
    image_path=diagram_path,
)
print("Step 1 (diagram) done. len =", len(current_html))

evidence_html = build_evidence_table_html("../sample_data/extraction_sheet.csv")
current_html = insert_html_via_review(
    SESSION_ID,
    current_html,
    instruction="Insert this table immediately after the Results section heading and its existing paragraph, introduced with a heading 'Table 1. Characteristics and results of included studies.'",
    html_to_insert=evidence_html,
)
print(
    "Step 2 (evidence) done. len =",
    len(current_html),
    "| fabricated:",
    "Please fill" in current_html,
)

search_html = build_search_strategy_html("../sample_data/search_strategy.csv")
current_html = insert_html_via_review(
    SESSION_ID,
    current_html,
    instruction="Insert this content as a new appendix section at the very end of the document, after the Discussion section.",
    html_to_insert=search_html,
)
print(
    "Step 3 (appendix) done. len =",
    len(current_html),
    "| fabricated:",
    "Please fill" in current_html,
)

rob_html = build_risk_of_bias_html("../sample_data/risk_of_bias.csv")
current_html = insert_html_via_review(
    SESSION_ID,
    current_html,
    instruction="Insert this risk-of-bias summary table immediately after Table 1, before the Discussion section.",
    html_to_insert=rob_html,
)
print(
    "Step 4 (risk-of-bias) done. len =",
    len(current_html),
    "| fabricated:",
    "Please fill" in current_html,
)

print("\nFinal check — 'Please fill' anywhere:", "Please fill" in current_html)
print("Final length:", len(current_html))
