"""Drafting-path LIVE test (plain HTTP, no LibreOffice needed, costs <= 1 op).

Sends a drafting-style instruction ("create X") the way the sidebar does and
verifies the client surfaces the created content as edit["draft_html"] when the
job completes with zero pending changes (the B6 behavior: creation bypasses the
approval gate). If the model instead proposes in-place edits, we reject them
(free) and report that this run did not exercise the draft path - both outcomes
are honest.

Needs SUPERDOCS_API_KEY or ~/.superdocs/agent_credentials.json.
Run: python3 tests/draft_live_test.py
"""
import base64
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "pythonpath"))
import superdocs_client as sc
import writeback

BASE = "Migration Plan"
# mirror the whole-doc flow (the wording that reliably triggers creation):
# upload a near-empty doc, then the exact message request_doc_edit sends
session = "sdext-drafttest-" + time.strftime("%Y%m%d-%H%M%S")
sc._call("POST", "/v1/documents/upload-base64", {
    "filename": "passage.html",
    "file_base64": base64.b64encode(
        f"<html><body><h1>{BASE}</h1></body></html>".encode()).decode(),
    "session_id": session,
})
edit = sc._open_edit(
    session,
    "create a plan to hit gym"
    "\n\nApply targeted edits to this document; change only what "
    "the instruction requires; do not add commentary or metadata.",
    lambda m: print("   ", m))
print("state:", edit["state"], "| pending:", len(edit["pending"]),
      "| response:", (edit.get("response") or "")[:120])

if edit["state"] == "awaiting_approval":
    sc.finalize(edit, False, progress=lambda m: print("   ", m))
    print("NOTE: model proposed in-place edits for this phrasing; rejected (free).")
    print("DRAFT LIVE TEST: SKIPPED (draft path not taken this run - not a failure)")
    sys.exit(0)

paras = writeback.html_paragraphs(edit.get("draft_html"))
checks = [
    ("job completed with no pending changes", not edit["pending"]),
    ("draft_html surfaced and non-empty", bool(paras)),
    ("draft differs from the uploaded passage",
     " ".join(paras) != writeback._norm(BASE)),
]
ok = True
for name, passed in checks:
    print(("PASS " if passed else "FAIL ") + name)
    ok = ok and passed
if ok:
    print("draft paragraphs:", len(paras), "| first:", paras[0][:80])
print("DRAFT LIVE TEST:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
