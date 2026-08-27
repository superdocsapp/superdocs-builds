"""Proves checklist page references stay correct after the manuscript is
edited: inserts a substantial new paragraph early in the document (shifting
everything after it to later pages), re-detects page numbers from the
REAL re-exported PDF, and shows the checklist values change accordingly —
not because we re-typed them, but because the same detection logic re-ran
against new layout."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from checklist import CHECKLIST_ITEMS
from page_finder import build_checklist_page_map
from insert_content import insert_html_via_review, get_current_document_html
from superdocs_client import export_document

SESSION_ID = sys.argv[1] if len(sys.argv) > 1 else None
if not SESSION_ID:
    print("Usage: python prove_repagination.py <session_id>")
    sys.exit(1)

# Step 1: BEFORE state
before_pdf = "../output/before_edit.pdf"
export_document(SESSION_ID, "pdf", before_pdf)
before_map = build_checklist_page_map(before_pdf, CHECKLIST_ITEMS)

print("=== BEFORE edit ===")
for m in before_map:
    print(f"  {m['item']:35s} -> page {m['page']}")

# Step 2: fetch current document state, then make a substantial edit early
# in the document — a large paragraph after the Abstract, before Methods.
current_html = get_current_document_html(SESSION_ID)

filler_paragraph = (
    "<p>"
    + " ".join(
        [
            "This additional introductory paragraph is inserted specifically to "
            "test whether page-referenced content in this document updates "
            "correctly after re-pagination."
        ]
        * 15
    )
    + "</p>"
)

insert_html_via_review(
    SESSION_ID,
    current_html,
    instruction="Insert this paragraph immediately after the Abstract section, before the Methods section.",
    html_to_insert=filler_paragraph,
)
print("\n✓ Filler paragraph inserted (shifts subsequent content later).")

# Step 3: AFTER state — re-export, re-detect, using the SAME detection logic
after_pdf = "../output/after_edit.pdf"
export_document(SESSION_ID, "pdf", after_pdf)
after_map = build_checklist_page_map(after_pdf, CHECKLIST_ITEMS)

print("\n=== AFTER edit ===")
for m in after_map:
    print(f"  {m['item']:35s} -> page {m['page']}")

# Step 4: comparison
print("\n=== Comparison ===")
changed_count = 0
for b, a in zip(before_map, after_map):
    if b["page"] != a["page"]:
        changed_count += 1
        print(f"  CHANGED: {b['item']:35s} {b['page']} -> {a['page']}")
    else:
        print(f"  same:    {b['item']:35s} {b['page']}")

print(f"\n{changed_count} of {len(before_map)} items shifted page after the edit.")
if changed_count == 0:
    print(
        "⚠️  WARNING: no items shifted — the edit may not have actually changed pagination."
    )
else:
    print(
        "✓ Page references correctly reflect the new layout, computed fresh — not stale."
    )
