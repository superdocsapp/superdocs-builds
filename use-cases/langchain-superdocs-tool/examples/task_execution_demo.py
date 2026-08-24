"""
SuperDocs Live API: Background Task Creation, Job Polling & Execution Lifecycle.

Demonstrates:
1. POST /v1/chat/async: Create asynchronous document generation tasks.
2. GET /v1/jobs/{job_id}: Poll real-time progress (0% -> 100%) and step execution.
3. GET /v1/jobs: List active and historical jobs in the account queue.
4. Exporting generated documents to DOCX, PDF, and Markdown.
"""

import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from superdocs_langchain.client import SuperDocsClient


def main():
    print("=" * 75)
    print(" 🚀 SuperDocs Live API: Asynchronous Task Creation & Execution Demo")
    print("=" * 75)

    client = SuperDocsClient()
    print(f"• Target Endpoint : {client.base_url}")
    print(f"• Active Mode     : {'Offline Mock' if client.offline else 'Live SuperDocs Cloud API'}")

    whoami = client.get_whoami()
    if whoami.success and whoami.data:
        d = whoami.data
        print(f"• Verified Account: Tier '{d.get('tier')}' | Quota: {d.get('remaining')}/{d.get('monthly_limit')} ops left")
    print("-" * 75)

    # 1. Create a live asynchronous task
    session_id = f"task-demo-{int(time.time())}"
    print(f"\n[1] Creating Background Task via POST /v1/chat/async in session '{session_id}'...")

    task_instruction = (
        "Create an Enterprise AI Security Policy with: "
        "1. Executive Summary and Governance Scope, "
        "2. LLM Prompt Injection & Data Leakage Prevention Controls, "
        "3. Model Registry & Audit Trail Guidelines."
    )

    create_res = client.create_task(
        session_id=session_id,
        message=task_instruction,
        model_tier="core",
    )

    if not create_res.success or not create_res.data:
        print(f"❌ Failed to create task: {create_res.message}")
        return

    job_id = create_res.data.get("job_id")
    print(f"✅ Task created successfully!")
    print(f"   ↳ Job ID: {job_id}")
    print(f"   ↳ Initial Status: {create_res.data.get('status', 'pending')}")

    # 2. Poll and monitor execution progress
    print(f"\n[2] Polling Task Execution Progress via GET /v1/jobs/{job_id}...")
    start_ts = time.time()
    final_job_data = None

    while time.time() - start_ts < 120:
        status_res = client.get_task_status(job_id)
        if status_res.success and status_res.data:
            job = status_res.data
            status = job.get("status")
            progress = job.get("progress", 0)
            elapsed = round(time.time() - start_ts, 1)

            print(f"   ↳ [{elapsed}s] Status: {status.upper():<12} | Progress: {progress:>3}%")

            if status in ("completed", "failed", "cancelled", "awaiting_approval"):
                final_job_data = job
                break

        time.sleep(2)

    if not final_job_data or final_job_data.get("status") != "completed":
        print(f"❌ Job ended with status: {final_job_data.get('status') if final_job_data else 'timeout'}")
        return

    result_payload = final_job_data.get("result") or {}
    ai_reply = result_payload.get("response", "Document created.")
    print(f"\n✅ Task Completed Successfully in {round(time.time() - start_ts, 1)} seconds!")
    print(f"• AI Execution Summary: {ai_reply}")

    # 3. List recent jobs from account queue
    print(f"\n[3] Querying Account Task Queue via GET /v1/jobs...")
    jobs_res = client.list_tasks()
    if jobs_res.success and jobs_res.data:
        jobs = jobs_res.data.get("jobs", [])
        print(f"• Total Jobs in Queue: {len(jobs)}")
        for j in jobs[:5]:
            print(f"   - Job {j.get('job_id')} | Session: {j.get('session_id')} | Status: {j.get('status')} ({j.get('progress', 0)}%)")

    # 4. Export finalized document
    print(f"\n[4] Exporting Final Document via POST /v1/documents/export...")
    export_res = client.export_document(session_id=session_id, export_format="markdown")
    if export_res.success:
        print(f"✅ Markdown export ready ({export_res.data.get('length', 0)} characters).")
        preview = (export_res.data.get("content") or "")[:350]
        print(f"\n--- Document Preview ---\n{preview}\n...")

    print("\n" + "=" * 75)
    print(" 🎉 End-to-end SuperDocs API Task Creation & Execution Succeeded!")
    print("=" * 75)


if __name__ == "__main__":
    main()
