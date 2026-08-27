"""Tests whether evidence-table fabrication is caused by turn position
(N-th sequential call in a session) vs accumulated document size, by running
the SAME evidence-table insertion at different points in a chain."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_tables import build_evidence_table_html
from insert_content import insert_html_via_review
from superdocs_client import (
    upload_document,
    new_session_id,
    resolve_any_pending_approval,
)


def evidence_instruction():
    evidence_html = build_evidence_table_html("../sample_data/extraction_sheet.csv")
    return evidence_html


SESSION_ID = new_session_id("turn-position-test")
resolve_any_pending_approval(SESSION_ID, approve=False)
upload_result = upload_document("../sample_data/draft_manuscript.html", SESSION_ID)
current_html = upload_result["html"]
print(f"Initial html length: {len(current_html)} chars")

evidence_html = evidence_instruction()

# Run 3 filler no-op-ish turns first (small, harmless edits) to simulate
# being deep in a session, WITHOUT inserting the diagram/appendix content
# that grows the document — isolates "turn count" from "document size".
for i in range(3):
    current_html = insert_html_via_review(
        SESSION_ID,
        current_html,
        instruction=f"Add the word 'checkpoint{i}' in a comment-like small tag at the very end of the document, after Discussion.",
        html_to_insert=f'<p style="display:none">checkpoint{i}</p>',
    )
    print(f"After filler turn {i}: html length = {len(current_html)} chars")

print("\nNow attempting evidence table insertion as the 4th sequential call...")
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
