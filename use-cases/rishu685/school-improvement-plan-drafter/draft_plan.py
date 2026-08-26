#!/usr/bin/env python3
"""
School Improvement Plan Drafter
Surfaces used: Chat, Images, Templates, Multi-Document, Review (HITL), Export
"""
import os
import sys
import json
import time
import base64
import io
import httpx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from docx import Document
from docx.shared import Pt, RGBColor
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
def run_chat_async(client, session_id, message, approval_mode="approve_all", image_attachments=None, prior_html=None):
    payload = {
        "session_id": session_id,
        "message": message,
        "approval_mode": approval_mode
    }
    if prior_html:
        payload["document_html"] = prior_html
    if image_attachments:
        payload["image_attachments"] = image_attachments

    res = client.post(f"{BASE_URL}/v1/chat/async", json=payload, headers=HEADERS_JSON)
    if res.status_code != 200:
        print(f"Failed to start async chat: {res.text[:300]}")
        sys.exit(1)

    job_id = res.json().get("job_id")
    print(f"  Job started: {job_id}")

    approved_job_ids = set()  # track which jobs we already approved

    while True:
        time.sleep(5)
        job_res = client.get(f"{BASE_URL}/v1/jobs/{job_id}?compact=true", headers=HEADERS_AUTH)
        if job_res.status_code != 200:
            print(f"Failed to poll job: {job_res.text[:200]}")
            sys.exit(1)

        job_data = job_res.json()
        status = job_data.get("status")
        print(f"  Status: {status} ({job_data.get('progress')}%)")

        if status == "awaiting_approval" and job_id not in approved_job_ids:
            # HITL Review Surface: approve all pending changes once
            meta = job_data.get("metadata") or {}
            pending = meta.get("pending_changes") or []
            print(f"  ⏸  HITL Review: {len(pending)} proposed change(s) awaiting approval")
            approved_job_ids.add(job_id)

            if pending:
                for change in pending:
                    change_id = change.get("change_id") or change.get("id")
                    print(f"     ✅ Approving change: {change_id}")
                    approve_res = client.post(
                        f"{BASE_URL}/v1/chat/{session_id}/approve",
                        json={"job_id": job_id, "change_id": change_id, "approved": True},
                        headers=HEADERS_JSON
                    )
                    if approve_res.status_code != 200:
                        print(f"  Approval failed: {approve_res.text[:200]}")
            else:
                # Batch approve all at once
                print(f"     ✅ Batch approving all changes")
                client.post(
                    f"{BASE_URL}/v1/chat/{session_id}/approve",
                    json={"job_id": job_id, "approved": True},
                    headers=HEADERS_JSON
                )
            time.sleep(3)  # allow server to resume after approval

        elif status == "completed":
            full_res = client.get(f"{BASE_URL}/v1/jobs/{job_id}", headers=HEADERS_AUTH)
            return full_res.json().get("result", {})

        elif status in ["failed", "cancelled"]:
            print(f"  Job failed: {job_data.get('error')}")
            sys.exit(1)


# ─────────────────────────── SURFACE 1: Build .docx Template ──────────────────
def create_sip_template_docx():
    """Build a mandated School Improvement Plan .docx template."""
    doc = Document()

    # Title
    title = doc.add_heading("School Improvement Plan", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.runs[0]
    run.font.color.rgb = RGBColor(0x20, 0x29, 0x40)

    doc.add_paragraph("School Name: ____________________________   Academic Year: ____________")
    doc.add_paragraph("Principal: ____________________________   Date Submitted: ____________")
    doc.add_paragraph("")

    doc.add_heading("Section 1: Needs Assessment", level=1)
    doc.add_paragraph("[NEEDS ASSESSMENT TABLE: Current year metrics vs. prior year baseline]")

    doc.add_heading("Section 2: Annual Target Goals", level=1)
    doc.add_paragraph("[MEASURABLE GOALS: Math / Reading / Attendance targets with % benchmarks]")

    doc.add_heading("Section 3: Evidence-Based Strategies", level=1)
    doc.add_paragraph("[STRATEGIES: Research-cited interventions per goal area]")

    doc.add_heading("Section 4: Resource Allocation", level=1)
    doc.add_paragraph("[RESOURCE TABLE: Budget line items per strategy]")

    doc.add_heading("Section 5: Monitoring Schedule", level=1)
    doc.add_paragraph("[MONITORING TABLE: Check-in dates, responsible parties, metrics]")

    doc.add_heading("Section 6: Mid-Year Progress Report", level=1)
    doc.add_paragraph("[PROGRESS STATUS: Goal-by-goal status at mid-year review]")

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


# ─────────────────────────── SURFACE 2: Build Assessment Chart Image ──────────
def create_assessment_chart_b64():
    """Generate a bar chart comparing 2025 vs 2026 assessment metrics."""
    categories = ["Math Proficiency", "Reading Proficiency", "Attendance\n(non-chronic absent)"]
    vals_2025 = [58, 62, 86]
    vals_2026 = [61, 68, 89]

    x = range(len(categories))
    fig, ax = plt.subplots(figsize=(8, 4.5))
    fig.patch.set_facecolor("#FBF9F6")
    ax.set_facecolor("#FBF9F6")

    bars1 = ax.bar([i - 0.2 for i in x], vals_2025, 0.35, label="2025 Baseline", color="#8B6240")
    bars2 = ax.bar([i + 0.2 for i in x], vals_2026, 0.35, label="2026 Current",  color="#1DA851")

    ax.set_title("Pinewood Elementary: Assessment Data 2025 vs 2026",
                 fontsize=13, fontweight="bold", color="#202940", pad=12)
    ax.set_ylabel("% Students", color="#202940")
    ax.set_ylim(0, 100)
    ax.set_xticks(list(x))
    ax.set_xticklabels(categories, color="#202940")
    ax.tick_params(colors="#202940")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(loc="lower right")

    for bar in bars1:
        ax.annotate(f"{bar.get_height()}%",
                    xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=9, color="#202940")
    for bar in bars2:
        ax.annotate(f"{bar.get_height()}%",
                    xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=9, color="#202940")

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close()
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def main():
    print("=== SuperDocs School Improvement Plan Drafter ===\n")
    print("Surfaces: Chat | Images | Templates | Multi-Document | Review (HITL) | Export\n")

    client = httpx.Client(timeout=300.0)

    # ── SURFACE: Templates ────────────────────────────────────────────────────
    print("Step 1: Creating & uploading SIP Word template...")
    template_bytes = create_sip_template_docx()
    tpl_res = client.post(
        f"{BASE_URL}/v1/templates/upload",
        files={"file": ("sip_template.docx", template_bytes,
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

    # ── SURFACE: Images ───────────────────────────────────────────────────────
    print("Step 3: Generating assessment comparison chart (image surface)...")
    chart_b64 = create_assessment_chart_b64()
    chart_bytes = base64.b64decode(chart_b64)
    image_attachments = [{
        "id": "assessment_chart_2026",
        "name": "assessment_chart_2026.png",
        "base64Data": chart_b64,
        "mimeType": "image/png",
        "size": len(chart_bytes)
    }]
    print("  Assessment chart generated.\n")

    # ── Upload prior plan ─────────────────────────────────────────────────────
    prior_plan_path = os.path.join(os.path.dirname(__file__), "sample_prior_plan.txt")
    with open(prior_plan_path, "r") as f:
        prior_plan_content = f.read()
    prior_html = f"<div><h1>2025 School Improvement Plan — Pinewood Elementary</h1><pre>{prior_plan_content}</pre></div>"

    print("Step 4: Uploading 2025 baseline plan and drafting 2026 plan from template + assessment chart...")
    draft_msg = (
        "Using the uploaded SIP template structure, draft the 2026 School Improvement Plan for Pinewood Elementary. "
        "Use the assessment bar chart in the attached image to fill in the Needs Assessment section with a comparison table. "
        "Set new targets: Math → 70%, Reading → 75%, Attendance (non-chronic absentee rate) → below 8%. "
        "Include evidence-based strategies with real research citations, a resource allocation table, and a monitoring schedule."
    )
    result = run_chat_async(
        client, session_id, draft_msg,
        approval_mode="approve_all",
        image_attachments=image_attachments,
        prior_html=prior_html
    )
    print(f"  Draft complete: {result.get('response', '')[:200]}...\n")

    # ── SURFACE: Review (HITL) ─────────────────────────────────────────────────
    print("Step 5: Mid-year update with HITL Review mode (ask_every_time)...")
    update_msg = (
        "Mid-year review: Update the plan to mark the Math Proficiency goal as IN-PROGRESS "
        "and the Reading Proficiency goal as COMPLETED. Keep all historical goal data intact. "
        "Then generate a 1-page Board Progress Report as a second document in this session."
    )
    result = run_chat_async(
        client, session_id, update_msg,
        approval_mode="ask_every_time"  # HITL: pause for review before each edit
    )
    print(f"  Mid-year update complete: {result.get('response', '')[:200]}...\n")

    # ── SURFACE: Export ───────────────────────────────────────────────────────
    print("Step 6: Exporting final plan to PDF...")
    export_res = client.post(
        f"{BASE_URL}/v1/documents/export",
        json={
            "session_id": session_id,
            "format": "pdf",
            "filename": "Pinewood_School_Improvement_Plan_2026.pdf"
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
        out_filename = "Pinewood_School_Improvement_Plan_2026.pdf"
        with open(out_filename, "wb") as f:
            f.write(export_res.content)
        print(f"  Export complete! Saved locally to: {out_filename}")

    print(f"\n  Adopt Session URL: https://use.superdocs.app/?adopt={session_id}")
    print("\n✅ School Improvement Plan Drafter completed successfully!")
    print("   Surfaces used: Chat ✓  Images ✓  Templates ✓  Multi-Document ✓  Review (HITL) ✓  Export ✓")


if __name__ == "__main__":
    main()
