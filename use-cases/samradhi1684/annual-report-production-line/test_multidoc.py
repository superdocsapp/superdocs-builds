import json
import os
import requests

API_KEY = os.environ["SUPERDOCS_API_KEY"]

BASE_URL = "https://api.superdocs.app"
SESSION_ID = "annual-report-multidoc-test"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
}

DOCUMENTS = [
    ("chair-statement.html", "Chair Statement", "draft", "replace"),
    ("strategy.html", "Strategy", "editorial_review", "new_focused"),
    ("business-review.html", "Business Review", "finance_review", "new_focused"),
    ("governance.html", "Governance", "legal_review", "new_focused"),
    ("financial-statements.html", "Financial Statements", "approved", "new_focused"),
]

STATE_FILE = "report_state.json"


def upload(path: str, open_mode: str):
    print(f"\nUploading {path}...")

    with open(path, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/v1/documents/upload",
            headers=HEADERS,
            files={"file": f},
            data={
                "session_id": SESSION_ID,
                "open_mode": open_mode,
            },
            timeout=120,
        )

    print("Status:", response.status_code)
    response.raise_for_status()

    return response.json()


state = {
    "report_title": "Annual Report 2026",
    "session_id": SESSION_ID,
    "documents": {},
}


for filename, section, stage, open_mode in DOCUMENTS:

    data = upload(
        f".\\documents\\{filename}",
        open_mode,
    )

    document_id = data.get("document_id")

    state["documents"][section] = {
        "filename": filename,
        "document_id": document_id,
        "stage": stage,
    }

    print(f"  {section}")
    print(f"  ID: {document_id}")
    print(f"  Stage: {stage}")


with open(STATE_FILE, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2)


print("\n" + "=" * 70)
print("REPORT STATE SAVED")
print("=" * 70)

print(f"State file: {STATE_FILE}")

for section, document in state["documents"].items():
    print(
        f"  {section}: "
        f"{document['document_id']} "
        f"({document['stage']})"
    )