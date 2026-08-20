"""
sync_design.py — "designs stay linked": re-pulls a Canva design, and
if the copy actually changed since the last sync, pushes a TARGETED
update to the existing SuperDocs session rather than regenerating the
whole document. If nothing changed, this costs ZERO SuperDocs
operations.

Run this any time after editing the source Canva design.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import time
import hashlib
import difflib
from datetime import datetime, timezone
from pathlib import Path

import requests

from design_links import get_link, update_link
from extract_content import extract_text

CANVA_TOKEN = os.environ["CANVA_ACCESS_TOKEN"]
SUPERDOCS_KEY = os.environ["SUPERDOCS_API_KEY"]
DESIGN_ID = "DAHSiXKMgD4"

CANVA_HEADERS = {"Authorization": f"Bearer {CANVA_TOKEN}", "Content-Type": "application/json"}
SUPERDOCS_HEADERS = {"Authorization": f"Bearer {SUPERDOCS_KEY}", "Content-Type": "application/json"}


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def export_and_extract_current_text() -> str:
    response = requests.post(
        "https://api.canva.com/rest/v1/exports",
        headers=CANVA_HEADERS,
        json={"design_id": DESIGN_ID, "format": {"type": "pdf"}},
    )
    job_id = response.json().get("job", {}).get("id")

    for _ in range(30):
        poll = requests.get(f"https://api.canva.com/rest/v1/exports/{job_id}", headers=CANVA_HEADERS)
        data = poll.json()
        status = data.get("job", {}).get("status")
        if status == "success":
            pdf_url = data["job"]["urls"][0]
            pdf_bytes = requests.get(pdf_url).content
            tmp_path = Path("sync_temp.pdf")
            tmp_path.write_bytes(pdf_bytes)
            text = extract_text(tmp_path)
            tmp_path.unlink()
            return text
        if status == "failed":
            raise RuntimeError(f"Canva export failed: {data}")
        time.sleep(2)
    raise TimeoutError("Canva export did not complete in time")


def main():
    link = get_link(DESIGN_ID)
    current_text = export_and_extract_current_text()
    current_hash = content_hash(current_text)
    now = datetime.now(timezone.utc).isoformat()

    if link is None:
        session_id = f"canva-{DESIGN_ID}"
        update_link(DESIGN_ID, session_id, current_hash, current_text, now)
        print(f"No prior sync found. Registered baseline link: design {DESIGN_ID} -> session {session_id}")
        print("(Snapshot saved - the NEXT sync will show a real diff against this baseline.)")
        return

    if current_hash == link["last_content_hash"]:
        print(f"No changes detected since last sync ({link['last_synced_at']}).")
        print("Skipping SuperDocs call entirely - zero operations spent.")
        return

    print(f"Change detected since last sync ({link['last_synced_at']}).")

    old_text = link.get("last_text_snapshot", "")
    diff = list(difflib.unified_diff(
        old_text.splitlines(), current_text.splitlines(),
        lineterm="", n=0,
    ))
    print("\nDetected diff:")
    for line in diff:
        print(f"  {line}")

    session_id = link["session_id"]
    instruction = (
        "The source design for this document has been updated. Here is the new, current "
        f"copy from the design:\n\n{current_text}\n\n"
        "Update ONLY the parts of the existing document that reflect outdated information "
        "from the old version. Do not regenerate or restructure sections that are still accurate."
    )
    response = requests.post(
        "https://api.superdocs.app/v1/chat",
        headers=SUPERDOCS_HEADERS,
        json={"message": instruction, "session_id": session_id},
    )
    data = response.json()
    print(f"\nSuperDocs update status: {response.status_code}")
    print(f"AI response: {data.get('response')}")
    print(f"Operations charged: {data.get('usage', {}).get('ops_charged')}")

    update_link(DESIGN_ID, session_id, current_hash, current_text, now)
    print("\nLink registry updated (with snapshot for next diff).")


if __name__ == "__main__":
    main()