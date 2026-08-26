"""
inspect_job.py — prints the FULL raw response for one job ID, so we can
see exactly why it settled with 0 pending_changes instead of guessing.

Usage:
    python inspect_job.py <job_id>
"""
import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

if len(sys.argv) < 2:
    print("Usage: python inspect_job.py <job_id>")
    sys.exit(1)

job_id = sys.argv[1]
api_key = os.environ["SUPERDOCS_API_KEY"]
headers = {"Authorization": f"Bearer {api_key}"}

resp = requests.get(f"https://api.superdocs.app/v1/jobs/{job_id}", headers=headers)
print("status code:", resp.status_code)
print(json.dumps(resp.json(), indent=2))