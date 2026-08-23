"""
apply_and_export.py — manual recovery tool.

Not part of the normal flow: run_build1.py now does this verification
automatically via SuperDocsClient.verify_and_get_final_html() (see that
module's docstring for the real bug this exists to work around). This
script is kept as a standalone fallback for manually re-exporting a
session that's already had changes approved, e.g. if run_build1.py's
own export step ever fails partway through and you want to recover
without re-running the whole flow (which would re-trigger the AI edit
and approval steps again).

Usage:
    python apply_and_export.py <SESSION_ID> <JOB_ID> [output_filename]

HONEST NOTE: earlier versions of this script had SESSION_ID and JOB_ID
hardcoded from a specific past run, which meant a later run of this
script silently used stale, unrelated IDs. Fixed here to take them as
required CLI arguments instead, so it can never silently run against
the wrong session/job.
"""

import sys
import requests
import os

API_KEY = os.environ["SUPERDOCS_API_KEY"]
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python apply_and_export.py <SESSION_ID> <JOB_ID> [output_filename]")
        sys.exit(1)

    session_id = sys.argv[1]
    job_id = sys.argv[2]
    output_filename = sys.argv[3] if len(sys.argv) > 3 else "menu-costing-sheet-updated"

    hist = requests.get(
        f"https://api.superdocs.app/v1/sessions/{session_id}/history", headers=HEADERS
    ).json()
    doc_html = hist["document_state"]["html_content"]
    print("current doc length:", len(doc_html))

    job = requests.get(f"https://api.superdocs.app/v1/jobs/{job_id}", headers=HEADERS).json()
    pending = job.get("metadata", {}).get("pending_changes") or []
    if not pending:
        print(f"No pending changes found for job {job_id} (status={job.get('status', job.get('detail'))}). "
              f"Nothing to apply locally — exporting the session's current state as-is.")

    applied = 0
    for c in pending:
        chunk_id = c["chunk_id"]
        if c["new_html"] in doc_html:
            applied += 1  # already landed server-side, nothing to do
        elif c["old_html"] in doc_html:
            doc_html = doc_html.replace(c["old_html"], c["new_html"], 1)
            applied += 1
        else:
            print(f"WARNING: neither old_html nor new_html for chunk {chunk_id} found verbatim in doc")

    print(f"applied/verified {applied}/{len(pending)} changes")

    resp = requests.post(
        "https://api.superdocs.app/v1/documents/export",
        headers=HEADERS,
        json={
            "html": doc_html,
            "format": "docx",
            "options": {"filename": output_filename},
        },
    )
    print("export status:", resp.status_code)
    if resp.status_code == 200:
        with open(f"{output_filename}.docx", "wb") as f:
            f.write(resp.content)
        print(f"saved: {output_filename}.docx")
    else:
        print("export body:", resp.text[:500])


if __name__ == "__main__":
    main()
