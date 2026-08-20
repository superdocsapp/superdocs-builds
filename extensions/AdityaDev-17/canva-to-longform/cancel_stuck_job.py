"""
cancel_stuck_job.py — cancels the leftover awaiting_approval job from
the earlier 422 bug, so the session is clean before retrying.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import requests

API_KEY = os.environ["SUPERDOCS_API_KEY"]
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
SESSION_ID = "canva-approval-DAHSiXKMgD4"

response = requests.get(f"https://api.superdocs.app/v1/sessions/{SESSION_ID}/jobs", headers=HEADERS)
jobs = response.json().get("jobs", [])

print(f"Found {len(jobs)} job(s) in this session:")
for job in jobs:
    print(f"  {job.get('job_id')}  status={job.get('status')}")

active = [j for j in jobs if j.get("status") in ("pending", "in_progress", "awaiting_approval")]
for job in active:
    job_id = job["job_id"]
    print(f"\nCancelling {job_id}...")
    cancel_response = requests.post(f"https://api.superdocs.app/v1/jobs/{job_id}/cancel", headers=HEADERS)
    print(f"  status: {cancel_response.status_code}  {cancel_response.text[:200]}")