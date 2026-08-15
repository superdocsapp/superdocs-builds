"""Tests whether inserting the search-strategy appendix specifically,
immediately before the evidence-table step, triggers fabrication —
isolating content/instruction-adjacency from generic turn count."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_tables import build_evidence_table_html, build_search_strategy_html
from insert_content import insert_html_via_review
from superdocs_client import (
    upload_document,
    new_session_id,
    resolve_any_pending_approval,
)

SESSION_ID = new_session_id("appendix-then-evidence-test")
resolve_any_pending_approval(SESSION_ID, approve=False)
upload_result = upload_document("../sample_data/draft_manuscript.html", SESSION_ID)
current_html = upload_result["html"]
print(f"Initial html length: {len(current_html)} chars")

# Step matching the REAL pipeline exactly: search appendix first
search_html = build_search_strategy_html("../sample_data/search_strategy.csv")
current_html = insert_html_via_review(
    SESSION_ID,
    current_html,
    instruction="Insert this content as a new appendix section at the very end of the document, after the Discussion section.",
    html_to_insert=search_html,
)
print(f"After search appendix: html length = {len(current_html)} chars")
print("Appendix contains real PubMed data:", "PubMed" in current_html)

# Then evidence table, exactly as the real pipeline does
evidence_html = build_evidence_table_html("../sample_data/extraction_sheet.csv")
current_html = insert_html_via_review(
    SESSION_ID,
    current_html,
    instruction="Insert this table immediately after the Results section heading and its existing paragraph, introduced with a heading 'Table 1. Characteristics and results of included studies.'",
    html_to_insert=evidence_html,
)

print("\n--- Result ---")
print("Contains Alvarez (real):", "Alvarez" in current_html)
print("Contains 'Please fill' (fabricated):", "Please fill" in current_html)
print(f"Final html length: {len(current_html)} chars")

# Print the actual HTML around the Results section for visual inspection
import re

idx = current_html.find("Results")
print("\n--- HTML snippet around 'Results' ---")
print(current_html[max(0, idx - 50) : idx + 800])
