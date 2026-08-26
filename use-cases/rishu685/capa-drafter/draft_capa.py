#!/usr/bin/env python3
"""
Corrective-Action-Plan (CAPA) 8D Drafter
Surfaces used: Chat, Templates, Export
"""
import os
import sys
import json
import time
import io
import httpx
from docx import Document
from docx.shared import RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

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
HEADERS_JSON = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}
HEADERS_AUTH = {"Authorization": f"Bearer {API_KEY}"}


# ─────────────────────────── HELPER: Async Chat with Polling ──────────────────
def run_chat_async(client, session_id, message, prior_html=None):
    payload = {
        "session_id": session_id,
        "message": message,
        "approval_mode": "approve_all"
    }
    if prior_html:
        payload["document_html"] = prior_html

    res = client.post(f"{BASE_URL}/v1/chat/async", json=payload, headers=HEADERS_JSON)
    if res.status_code != 200:
        print(f"Failed to start async chat: {res.text[:300]}")
        sys.exit(1)

    job_id = res.json().get("job_id")
    print(f"  Job started: {job_id}")

    while True:
        time.sleep(4)
        job_res = client.get(f"{BASE_URL}/v1/jobs/{job_id}?compact=true", headers=HEADERS_AUTH)
        if job_res.status_code != 200:
            print(f"Failed to poll job: {job_res.text[:200]}")
            sys.exit(1)

        job_data = job_res.json()
        status = job_data.get("status")
        print(f"  Status: {status} ({job_data.get('progress')}%)")

        if status == "completed":
            full_res = client.get(f"{BASE_URL}/v1/jobs/{job_id}", headers=HEADERS_AUTH)
            return full_res.json().get("result", {})
        elif status in ["failed", "cancelled"]:
            print(f"  Job failed: {job_data.get('error')}")
            sys.exit(1)


# ─────────────────────────── SURFACE: Build .docx CAPA Template ───────────────
def create_capa_template_docx():
    """Build a standard 8D CAPA compliance .docx template."""
    doc = Document()

    title = doc.add_heading("8D Corrective Action Plan (CAPA)", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.runs[0]
    run.font.color.rgb = RGBColor(0x20, 0x29, 0x40)

    doc.add_paragraph("Incident Reference: ____________   Date Opened: ____________")
    doc.add_paragraph("Product / Process: ____________   Site: ____________")
    doc.add_paragraph("")

    disciplines = [
        ("D1", "Team Formation", "[List team members and their roles]"),
        ("D2", "Problem Description", "[Describe the defect: what, where, when, how many, impact]"),
        ("D3", "Containment Actions", "[Immediate actions taken to contain the problem]"),
        ("D4", "Root Cause Analysis", "[5-Why or Fishbone analysis — identify verified root cause]"),
        ("D5", "Corrective Actions", "[Permanent corrective actions selected and verified]"),
        ("D6", "Implementation & Validation", "[Implementation evidence and validation test results]"),
        ("D7", "Prevention Actions", "[Systemic changes to prevent recurrence]"),
        ("D8", "Closure & Team Recognition", "[Sign-off, closure date, team acknowledgement]"),
    ]

    for code, name, placeholder in disciplines:
        doc.add_heading(f"{code}: {name}", level=1)
        doc.add_paragraph(placeholder)
        doc.add_paragraph("")

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def main():
    print("=== SuperDocs CAPA 8D Drafter ===\n")
    print("Surfaces: Chat | Templates | Export\n")

    client = httpx.Client(timeout=300.0)

    # ── SURFACE: Templates ────────────────────────────────────────────────────
    print("Step 1: Creating & uploading CAPA 8D Word template...")
    template_bytes = create_capa_template_docx()
    tpl_res = client.post(
        f"{BASE_URL}/v1/templates/upload",
        files={"file": ("capa_8d_template.docx", template_bytes,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        headers=HEADERS_AUTH
    )
    if tpl_res.status_code != 200:
        print(f"Template upload failed: {tpl_res.text[:300]}")
        sys.exit(1)
    tpl_data = tpl_res.json()
    template_id = tpl_data.get("template_id") or tpl_data.get("id")
    print(f"  Template uploaded. ID: {template_id}\n")

    # ── Init session ──────────────────────────────────────────────────────────
    print("Step 2: Initializing session...")
    init_res = client.post(f"{BASE_URL}/v1/sessions/init", json={}, headers=HEADERS_JSON)
    if init_res.status_code != 200:
        print(f"Failed to init session: {init_res.text}")
        sys.exit(1)
    session_id = init_res.json().get("session_id")
    print(f"  Session ID: {session_id}\n")

    # ── SURFACE: Chat — populate 8D template with incident data ──────────────
    print("Step 3: Drafting complete 8D CAPA report from template + incident data...")
    full_capa_prompt = """Using the uploaded CAPA 8D template structure, fill in a complete professional compliance report with the following incident data:

D1 - Team:
- Lead: John Doe (Quality Manager)
- Member: Jane Smith (Production Supervisor)

D2 - Problem Description:
Adhesion failure observed on Labeling Line 4 packaging batches. Batch #404-90 (500 units) showed label peel-off within 24 hours of application.

D3 - Containment Actions:
- Quarantined affected batch #404-90
- Halted Labeling Line 4 operations pending inspection
- Notified downstream distribution to hold shipments

D4 - Root Cause Analysis:
5-Why Analysis:
1. Why did labels peel? → Low adhesive strength
2. Why low adhesive strength? → Low solvent concentration in adhesive compound
3. Why low solvent concentration? → Adhesive mixer ratio drifted by 12%
4. Why did the mixer drift? → High room humidity (>80% RH) degraded adhesive mix calibration
5. Why was humidity not controlled? → No environmental monitoring was in place for the labeling area

D5 - Corrective Actions:
- Recalibrated solvent mixer ratio to ±2% tolerance
- Adjusted adhesive supplier specification limits
- Installed humidity control system in labeling area

D6 - Implementation & Validation:
- Labels tested on 500 trial bottles on Line 4
- Zero label peel failures over 72-hour soak test
- Line 4 cleared for full production restart

D7 - Prevention Actions:
- Monthly calibration checks for all labeling line adhesive mixers added to maintenance SOP
- Humidity monitoring alerts configured (threshold: 75% RH)
- Updated SOP-LAB-04 to require pre-shift adhesive mix verification

D8 - Closure:
Closed by Quality Lead John Doe on 2026-08-25. All corrective actions verified effective. Team recognized for rapid containment and thorough root cause investigation.

Format each section with clear structure, professional language, and a summary table at the top."""

    template_init_html = "<div><h1>8D CAPA Compliance Report</h1><p>Incident: Labeling Line 4 — Adhesion Failure | Status: Open</p></div>"

    result = run_chat_async(client, session_id, full_capa_prompt, prior_html=template_init_html)
    print(f"  CAPA Report drafted: {result.get('response', '')[:200]}...\n")

    # ── SURFACE: Export ───────────────────────────────────────────────────────
    print("Step 4: Exporting CAPA report to PDF...")
    export_res = client.post(
        f"{BASE_URL}/v1/documents/export",
        json={
            "session_id": session_id,
            "format": "pdf",
            "filename": "CAPA_8D_Labeling_Line_Report.pdf"
        },
        headers=HEADERS_JSON
    )
    if export_res.status_code != 200:
        print(f"Export failed: {export_res.text[:200]}")
        sys.exit(1)

    content_type = export_res.headers.get("content-type", "")
    if "application/json" in content_type:
        export_data = export_res.json()
        download_url = export_data.get("download_url") or export_data.get("url")
        print(f"  Export complete! Download: {download_url}")
    else:
        out_filename = "CAPA_8D_Labeling_Line_Report.pdf"
        with open(out_filename, "wb") as f:
            f.write(export_res.content)
        print(f"  Export complete! Saved locally to: {out_filename}")

    print(f"\n  Adopt Session URL: https://use.superdocs.app/?adopt={session_id}")
    print("\n✅ CAPA 8D Drafter completed successfully!")
    print("   Surfaces used: Chat ✓  Templates ✓  Export ✓")


if __name__ == "__main__":
    main()
