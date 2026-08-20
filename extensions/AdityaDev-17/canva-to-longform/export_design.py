"""
export_design.py — requests an export of the design in two formats:
html_bundle (copy + visual/style structure) and png (print-quality
image). Export jobs are async - create, then poll until done.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import time
import json
import requests

ACCESS_TOKEN = os.environ["CANVA_ACCESS_TOKEN"]
DESIGN_ID = "DAHSiXKMgD4"
HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}


def create_export(format_type: str, extra: dict | None = None) -> str:
    body = {"design_id": DESIGN_ID, "format": {"type": format_type, **(extra or {})}}
    response = requests.post(
        "https://api.canva.com/rest/v1/exports",
        headers=HEADERS,
        json=body,
    )
    print(f"  create export ({format_type}) status: {response.status_code}")
    data = response.json()
    print(f"  {json.dumps(data, indent=2)[:500]}")
    return data.get("job", {}).get("id")


def poll_export(export_id: str, label: str) -> dict:
    print(f"\nPolling {label} export job {export_id}...")
    for attempt in range(30):
        response = requests.get(
            f"https://api.canva.com/rest/v1/exports/{export_id}",
            headers=HEADERS,
        )
        data = response.json()
        status = data.get("job", {}).get("status")
        print(f"  attempt {attempt+1}: status={status}")
        if status == "success":
            return data
        if status == "failed":
            print(f"  FAILED: {data}")
            return data
        time.sleep(2)
    print("  gave up after 30 attempts")
    return {}


print("=== Requesting HTML bundle export (copy + visual system) ===")
html_job_id = create_export("html_bundle")

print("\n=== Requesting PNG export (print-quality image) ===")
png_job_id = create_export("png")

if html_job_id:
    html_result = poll_export(html_job_id, "HTML bundle")
    print("\nHTML export result:")
    print(json.dumps(html_result, indent=2))

if png_job_id:
    png_result = poll_export(png_job_id, "PNG")
    print("\nPNG export result:")
    print(json.dumps(png_result, indent=2))