import os
import sys
import json
import time
import httpx

API_KEY = os.environ.get("SUPERDOCS_API_KEY")
if not API_KEY:
    try:
        with open("/Users/apple/.superdocs/agent_credentials.json") as f:
            creds = json.load(f)
            API_KEY = creds.get("api_key")
    except Exception:
        pass

if not API_KEY:
    print("Error: SUPERDOCS_API_KEY environment variable is not set.")
    sys.exit(1)

BASE_URL = "https://api.superdocs.app"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def run_chat_async(client, session_id, message, prior_html=None):
    payload = {
        "session_id": session_id,
        "message": message,
        "approval_mode": "approve_all"
    }
    if prior_html:
        payload["document_html"] = prior_html

    res = client.post(f"{BASE_URL}/v1/chat/async", json=payload, headers=HEADERS)
    if res.status_code != 200:
        print(f"Failed to start async chat: {res.text}")
        sys.exit(1)

    job_id = res.json().get("job_id")
    print(f"Job started: {job_id}")

    while True:
        time.sleep(4)
        job_res = client.get(f"{BASE_URL}/v1/jobs/{job_id}?compact=true", headers=HEADERS)
        if job_res.status_code != 200:
            print(f"Failed to poll job: {job_res.text}")
            sys.exit(1)

        job_data = job_res.json()
        status = job_data.get("status")
        print(f"  Status: {status} ({job_data.get('progress')}%)")

        if status == "completed":
            # Fetch full result once done
            full_res = client.get(f"{BASE_URL}/v1/jobs/{job_id}", headers=HEADERS)
            return full_res.json().get("result", {})
        elif status in ["failed", "cancelled"]:
            print(f"Job failed: {job_data.get('error')}")
            sys.exit(1)

def main():
    print("=== SuperDocs CAPA 8D Drafter ===\n")
    client = httpx.Client(timeout=300.0)

    # 1. Init session
    print("Step 1: Initializing session...")
    init_res = client.post(f"{BASE_URL}/v1/sessions/init", json={}, headers=HEADERS)
    if init_res.status_code != 200:
        print(f"Failed to init session: {init_res.text}")
        sys.exit(1)
    session_id = init_res.json().get("session_id")
    print(f"Session ID: {session_id}\n")

    # 2. Single combined call - all 8D sections at once
    print("Step 2: Drafting complete 8D CAPA report in one pass...")
    full_capa_prompt = """Create a complete professional 8D Corrective Action Plan (CAPA) report with the following data:

D1 - Team:
- Lead: John Doe (Quality Manager)
- Member: Jane Smith (Production Supervisor)

D2 - Problem Description:
Adhesion failure observed on Labeling Line 4 packaging batches (Batch #404-90). Labels were peeling off within 24 hours of application.

D3 - Containment Actions:
- Quarantined affected batch #404-90 (500 units)
- Halted Labeling Line 4 operations for inspection
- Notified downstream distribution to hold shipments

D4 - Root Cause Analysis:
Investigation determined low solvent concentration in the label adhesive compound caused by high room humidity (>80% RH) degrading the adhesive mix ratio. The automatic solvent mixer calibration had drifted by 12%.

D5 - Corrective Actions:
- Recalibrated automatic solvent mixer ratio to spec (±2% tolerance)
- Adjusted adhesive supplier specification limits
- Installed humidity control system in labeling area

D6 - Implementation & Validation:
- Labels tested on 500 trial bottles on Line 4
- Zero label peel failures observed over 72-hour soak test
- Line 4 cleared for full production restart

D7 - Prevention Actions:
- Monthly calibration checks scheduled for all labeling line adhesive mixers
- Added humidity monitoring alerts (threshold: 75% RH)
- Updated SOP-LAB-04 to include pre-shift adhesive mix verification

D8 - Closure:
Closed by Quality Lead John Doe on 2026-08-25. All corrective actions verified effective.

Format this as a professional compliance document with clear section headers, tables where appropriate, and a signature block."""

    result = run_chat_async(
        client,
        session_id,
        full_capa_prompt,
        "<div><h1>8D CAPA Compliance Report</h1><p>Incident: Labeling Line 4 Adhesion Failure</p></div>"
    )
    print(f"\nCAPA Report drafted successfully!")
    print(f"AI: {result.get('response', '')[:200]}...\n")

    # 3. Export as PDF
    print("Step 3: Exporting CAPA report to PDF...")
    export_res = client.post(
        f"{BASE_URL}/v1/documents/export",
        json={
            "session_id": session_id,
            "format": "pdf",
            "filename": "CAPA_8D_Labeling_Line_Report.pdf"
        },
        headers=HEADERS
    )
    if export_res.status_code != 200:
        print(f"Export failed: {export_res.text[:200]}")
        sys.exit(1)

    content_type = export_res.headers.get("content-type", "")
    if "application/json" in content_type:
        export_data = export_res.json()
        download_url = export_data.get("download_url") or export_data.get("url")
        print("Export Complete!")
        print(f"Download Link: {download_url}")
    else:
        out_filename = "CAPA_8D_Labeling_Line_Report.pdf"
        with open(out_filename, "wb") as f:
            f.write(export_res.content)
        print(f"Export Complete! Saved locally to: {out_filename}")

    print(f"\nAdopt Session URL: https://use.superdocs.app/?adopt={session_id}")
    print("\n✅ CAPA 8D Drafter completed successfully!")

if __name__ == "__main__":
    main()
