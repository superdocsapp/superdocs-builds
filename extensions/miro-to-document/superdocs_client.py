import os
from pathlib import Path
import json
import requests
from dotenv import load_dotenv


load_dotenv()

API_KEY = os.getenv("SUPERDOCS_API_KEY")
BASE_URL = "https://api.superdocs.app/v1"


def send_document_for_edit(
    html: str,
    session_id: str,
    instruction: str,
):
    if not API_KEY:
        raise RuntimeError(
            "SUPERDOCS_API_KEY is missing from .env"
        )

    response = requests.post(
        f"{BASE_URL}/chat",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
       json={
    "message": instruction,
    "session_id": session_id,
    "document_html": html,
    "approval_mode": "ask_every_time",
},
        timeout=120,
    )

    print("HTTP STATUS:", response.status_code)

    response.raise_for_status()

    return response.json()


if __name__ == "__main__":

    html_path = Path("output/miro_document.html")

    if not html_path.exists():
        raise FileNotFoundError(
            f"Could not find {html_path}"
        )

    html = html_path.read_text(
        encoding="utf-8"
    )

    result = send_document_for_edit(
        html=html,
        session_id="miro-approval-test-002",
        instruction=(
            "Edit ONLY the Customer Problems list. "
            "Improve the wording of the four Customer Problems items. "
            "Do not modify Questions, Ideas, the header, image, footer, "
            "or any other part of the document. "
            "Preserve every Miro source ID exactly. "
            "Preserve the existing section structure and HTML structure."
        ),
    )

    print("\n=== SUPERDOCS RESPONSE ===")

    print("Session:")
    print(result.get("session_id"))

    print("\nResponse:")
    print(result.get("response"))

    document_changes = result.get("document_changes") or {}

    print("\n=== FULL DOCUMENT CHANGES ===")
    print(json.dumps(document_changes, indent=2))

    print("\nRequires approval:")
    print(document_changes.get("requires_approval"))

    pending_changes = (
        document_changes.get("pending_changes")
        or []
    )

    print("\nPending changes:")
    print(len(pending_changes))

    for change in pending_changes:
        print(
            f"- change_id={change.get('change_id')}"
        )
        print(
            f"  operation={change.get('operation')}"
        )
        print(
            f"  chunk_id={change.get('chunk_id')}"
        )

    updated_html = document_changes.get(
        "updated_html"
    )

    if updated_html:
        output_path = Path(
            "output/superdocs_proposed.html"
        )

        output_path.write_text(
            updated_html,
            encoding="utf-8"
        )

        print(
            f"\n✅ Proposed HTML saved to: {output_path}"
        )

    else:
        print(
            "\n⏸️ No updated HTML yet."
        )

        print(
            "SuperDocs is waiting for approval."
        )