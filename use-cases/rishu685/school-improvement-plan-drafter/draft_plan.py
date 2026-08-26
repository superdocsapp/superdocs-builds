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
    print(f"Started async job: {job_id}. Polling progress...")
    
    while True:
        time.sleep(3)
        job_res = client.get(f"{BASE_URL}/v1/jobs/{job_id}", headers=HEADERS)
        if job_res.status_code != 200:
            print(f"Failed to get job status: {job_res.text}")
            sys.exit(1)
            
        job_data = job_res.json()
        status = job_data.get("status")
        print(f"Job status: {status} (progress: {job_data.get('progress')}%)")
        
        if status == "completed":
            return job_data.get("result", {})
        elif status in ["failed", "cancelled"]:
            print(f"Job failed or cancelled: {job_data.get('error')}")
            sys.exit(1)

def main():
    print("=== SuperDocs School Improvement Plan Drafter (Async) ===\n")
    
    prior_plan_path = os.path.join(os.path.dirname(__file__), "sample_prior_plan.txt")
    with open(prior_plan_path, "r") as f:
        prior_plan_content = f.read()

    client = httpx.Client(timeout=300.0)

    # 1. Start session
    print("Step 1: Initializing session on SuperDocs...")
    init_res = client.post(f"{BASE_URL}/v1/sessions/init", json={}, headers=HEADERS)
    if init_res.status_code != 200:
        print(f"Failed to init session: {init_res.text}")
        sys.exit(1)
    
    session_id = init_res.json().get("session_id")
    print(f"Session initialized. Session ID: {session_id}\n")

    # 2. Upload prior plan as document HTML
    print("Step 2: Uploading 2025 Prior Plan as context...")
    prior_html = f"<div><h1>2025 School Improvement Plan</h1><pre>{prior_plan_content}</pre></div>"
    result = run_chat_async(
        client,
        session_id,
        "Initialize this document as Pinewood Elementary 2025 prior plan.",
        prior_html
    )
    print("Prior plan uploaded successfully.\n")

    # 3. Draft new 2026 Plan from Current Assessment Data
    print("Step 3: Drafting new 2026 School Improvement Plan based on current metrics...")
    current_metrics = (
        "CURRENT METRICS (2026 Assessment):\n"
        "- Math Proficiency: 61% (improved from 58%)\n"
        "- Reading Proficiency: 68% (improved from 62%)\n"
        "- Chronic Absenteeism: 11% (reduced from 14%)\n"
    )
    
    draft_instruction = (
        f"Draft the new 2026 School Improvement Plan following a mandated structure:\n"
        f"1. Needs Assessment table containing the 2025 baseline metrics alongside these new 2026 metrics:\n{current_metrics}\n"
        f"2. Target Goals: Increase Math to 70%, Reading to 75%, and Attendance to <8%.\n"
        f"3. Resource allocation details and a monitoring table.\n"
        f"Keep the formatting clean and professional."
    )
    
    result = run_chat_async(client, session_id, draft_instruction)
    print("Draft generated successfully.")
    print(f"AI Response:\n{result.get('response')}\n")

    # 4. Mid-Year Update and Progress Report
    print("Step 4: Simulating Mid-Year Update & generating Board Progress Report tab...")
    update_instruction = (
        "Update the plan: mark the Math target as IN-PROGRESS and the Reading target as COMPLETED.\n"
        "Then, generate a clean 1-page Board Progress Report as a second tab/document in this session."
    )
    result = run_chat_async(client, session_id, update_instruction)
    print("Mid-Year update committed.")
    print(f"AI Response:\n{result.get('response')}\n")

    # 5. Export document
    print("Step 5: Exporting final document to PDF...")
    export_res = client.post(
        f"{BASE_URL}/v1/documents/export",
        json={
            "session_id": session_id,
            "format": "pdf",
            "filename": "Pinewood_School_Improvement_Plan_2026.pdf"
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
        out_filename = "Pinewood_School_Improvement_Plan_2026.pdf"
        with open(out_filename, "wb") as f:
            f.write(export_res.content)
        print(f"Export Complete! Saved locally to {out_filename}")
        
    print(f"Adopt Session URL: https://use.superdocs.app/?adopt={session_id}")

if __name__ == "__main__":
    main()
