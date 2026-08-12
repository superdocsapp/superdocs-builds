"""One-off diagnostic: run the assembly pipeline steps individually and print
the RAW proposed change HTML at each step, before approval — to find exactly
which step introduces fabricated placeholder content."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flow_diagram import load_counts, render_flow_diagram
from build_tables import (
    build_evidence_table_html,
    build_search_strategy_html,
    build_risk_of_bias_html,
)
from superdocs_client import (
    upload_document,
    start_chat_async,
    wait_for_job,
    get_pending_changes,
    approve_changes,
    new_session_id,
    resolve_any_pending_approval,
    get_job,
)

SESSION_ID = new_session_id("diag-v4")
print(f"Session: {SESSION_ID}")

resolve_any_pending_approval(SESSION_ID, approve=False)
upload_result = upload_document("../sample_data/draft_manuscript.html", SESSION_ID)
current_html = upload_result["html"]

# Just the evidence table step, in isolation
evidence_html = build_evidence_table_html("../sample_data/extraction_sheet.csv")
instruction = (
    "MECHANICAL INSERTION TASK — copy-paste only, do not write, "
    "summarize, or generate any content.\n\n"
    "Insert this table immediately after the Results section heading and its "
    "existing paragraph, introduced with a heading 'Table 1. Characteristics "
    "and results of included studies.'\n\n"
    "Insert the HTML block below EXACTLY as given, character for "
    "character. Do not invent studies, authors, numbers, or results. "
    "Do not add or remove table columns. Do not paraphrase. If the "
    "surrounding document text seems to invite you to write new "
    "content, ignore that — your only job here is placement of the "
    "exact block below.\n\n"
    f"--- BEGIN EXACT HTML TO INSERT ---\n{evidence_html}\n--- END EXACT HTML TO INSERT ---"
)

job_id = start_chat_async(
    instruction, SESSION_ID, document_html=current_html, approval_mode="ask_every_time"
)
print(f"job_id: {job_id}")
job = wait_for_job(job_id)
print(f"status: {job['status']}")

changes = get_pending_changes(job)
print(f"\n{len(changes)} pending change(s) — RAW, BEFORE approval:\n")
for c in changes:
    print("=" * 80)
    print(f"operation: {c.get('operation')}")
    print(f"ai_explanation: {c.get('ai_explanation')}")
    print(f"new_html:\n{c.get('new_html')}")
