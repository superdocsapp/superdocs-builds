import os
import requests
import json

API_KEY = os.environ["SUPERDOCS_API_KEY"]

BASE_URL = "https://api.superdocs.app"
SESSION_ID = "annual-report-2026"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

payload = {
    "message": (
        "Compare the revenue figures in the narrative document and "
        "the financial statements document. Identify any differences "
        "between them. Do not modify either document."
    ),
    "session_id": SESSION_ID,
    "approval_mode": "approve_all",
}

print("Asking SuperDocs to compare the two documents...")

response = requests.post(
    f"{BASE_URL}/v1/chat",
    headers=headers,
    json=payload,
    timeout=300,
)

print("Status:", response.status_code)
response.raise_for_status()

result = response.json()

print("\nRESPONSE:")
print(result.get("response"))

print("\nDOCUMENT CHANGES:")
print(json.dumps(result.get("document_changes"), indent=2))

print("\nSESSION:")
print(result.get("session_id"))