"""Tests whether export_document (by session_id) reflects the same state as
current_html we're chaining locally, by exporting immediately after EACH
step and checking the exported FILE itself — not just the in-memory HTML
string — for that step's expected content."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import docx as docx_lib
from build_tables import (
    build_evidence_table_html,
    build_search_strategy_html,
    build_risk_of_bias_html,
)
from flow_diagram import load_counts, render_flow_diagram
from insert_content import insert_html_via_review
from superdocs_client import (
    upload_document,
    export_document,
    new_session_id,
    resolve_any_pending_approval,
)


def check_export(session_id: str, label: str):
    path = export_document(
        session_id, format="docx", output_path=f"../output/divergence_{label}.docx"
    )
    doc = docx_lib.Document(path)
    text = "\n".join(p.text for p in doc.paragraphs)
    for t in doc.tables:
        for row in t.rows:
            text += " " + " ".join(c.text for c in row.cells)
    return text


SESSION_ID = new_session_id("divergence-test")
resolve_any_pending_approval(SESSION_ID, approve=False)

counts = load_counts("../sample_data/screening_counts.json")
diagram_path = render_flow_diagram(counts, "../output/flow_diagram_divtest.png")

upload_result = upload_document("../sample_data/draft_manuscript.html", SESSION_ID)
current_html = upload_result["html"]

current_html = insert_html_via_review(
    SESSION_ID,
    current_html,
    instruction="Insert the attached flow diagram image immediately after the Methods section.",
    image_path=diagram_path,
)
exported_text = check_export(SESSION_ID, "1_diagram")
print(
    f"After diagram — local HTML has diagram-related text: {'Study flow' in current_html or 'diagram' in current_html.lower()}"
)
print(
    f"After diagram — EXPORTED FILE has diagram-related text: {'diagram' in exported_text.lower()}"
)
print()

evidence_html = build_evidence_table_html("../sample_data/extraction_sheet.csv")
current_html = insert_html_via_review(
    SESSION_ID,
    current_html,
    instruction="Insert this table immediately after the Results section heading and its existing paragraph, introduced with a heading 'Table 1. Characteristics and results of included studies.'",
    html_to_insert=evidence_html,
)
exported_text = check_export(SESSION_ID, "2_evidence")
print(f"After evidence — local HTML has Alvarez: {'Alvarez' in current_html}")
print(f"After evidence — EXPORTED FILE has Alvarez: {'Alvarez' in exported_text}")
print()

search_html = build_search_strategy_html("../sample_data/search_strategy.csv")
current_html = insert_html_via_review(
    SESSION_ID,
    current_html,
    instruction="Insert this content as a new appendix section at the very end of the document, after the Discussion section.",
    html_to_insert=search_html,
)
exported_text = check_export(SESSION_ID, "3_appendix")
print(f"After appendix — local HTML has PubMed: {'PubMed' in current_html}")
print(f"After appendix — EXPORTED FILE has PubMed: {'PubMed' in exported_text}")
print()

rob_html = build_risk_of_bias_html("../sample_data/risk_of_bias.csv")
current_html = insert_html_via_review(
    SESSION_ID,
    current_html,
    instruction="Insert this risk-of-bias summary table immediately after Table 1, before the Discussion section.",
    html_to_insert=rob_html,
)
exported_text = check_export(SESSION_ID, "4_final")
print(f"After risk-of-bias — local HTML has PubMed: {'PubMed' in current_html}")
print(f"After risk-of-bias — EXPORTED FILE has PubMed: {'PubMed' in exported_text}")
print(f"After risk-of-bias — EXPORTED FILE has Alvarez: {'Alvarez' in exported_text}")
print(f"After risk-of-bias — EXPORTED FILE has S01/Low: {'S01' in exported_text}")
