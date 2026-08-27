"""Tests whether search-appendix immediately before risk-of-bias triggers
the same fabrication pattern seen with search-appendix -> evidence-table."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_tables import build_search_strategy_html, build_risk_of_bias_html
from insert_content import insert_html_via_review
from superdocs_client import (
    upload_document,
    new_session_id,
    resolve_any_pending_approval,
)

SESSION_ID = new_session_id("appendix-then-rob-test")
resolve_any_pending_approval(SESSION_ID, approve=False)
upload_result = upload_document("../sample_data/draft_manuscript.html", SESSION_ID)
current_html = upload_result["html"]

search_html = build_search_strategy_html("../sample_data/search_strategy.csv")
current_html = insert_html_via_review(
    SESSION_ID,
    current_html,
    instruction="Insert this content as a new appendix section at the very end of the document, after the Discussion section.",
    html_to_insert=search_html,
)
print("After search appendix — contains PubMed:", "PubMed" in current_html)

rob_html = build_risk_of_bias_html("../sample_data/risk_of_bias.csv")
current_html = insert_html_via_review(
    SESSION_ID,
    current_html,
    instruction="Insert this risk-of-bias summary table immediately after the Results section, before the Discussion section.",
    html_to_insert=rob_html,
)

print("\n--- Result ---")
print("Contains real S01/Low (real):", "S01" in current_html and "Low" in current_html)
print("Contains 'Please fill' (fabricated):", "Please fill" in current_html)
