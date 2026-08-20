"""
resolve_stuck_job.py — properly resolves the job stuck in
awaiting_approval. Real bug chain, now fully understood: cancel_job
refuses jobs in this state (contradicting the 409 error's own
suggested_action), and the approve endpoint requires job_id in the
body - not documented in the endpoint description we read, only
discovered via the actual 422 validation error. Both worth reporting.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import requests

API_KEY = os.environ["SUPERDOCS_API_KEY"]
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
SESSION_ID = "canva-approval-DAHSiXKMgD4"
STUCK_JOB_ID = "200a3f8d-db1c-49c4-8a19-22af47b14aa2"

response = requests.get(f"https://api.superdocs.app/v1/jobs/{STUCK_JOB_ID}", headers=HEADERS)
data = response.json()
pending = data.get("metadata", {}).get("pending_changes", [])
print(f"Job status: {data.get('status')}")
print(f"Pending changes: {len(pending)}")

if len(pending) == 1:
    body = {"job_id": STUCK_JOB_ID, "approved": False}
else:
    body = {"job_id": STUCK_JOB_ID, "changes": [{"change_id": c.get("change_id"), "approved": False} for c in pending]}

approve_response = requests.post(
    f"https://api.superdocs.app/v1/chat/{SESSION_ID}/approve",
    headers=HEADERS,
    json=body,
)
print(f"\nResolve status: {approve_response.status_code}")
print(f"Body: {approve_response.text[:500]}")