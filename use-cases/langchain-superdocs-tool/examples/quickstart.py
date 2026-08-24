"""
SuperDocs Quickstart: Live API Chat, Task Creation & Async Execution.

Demonstrates:
1. Connecting to live SuperDocs API and verifying account quota (/v1/agents/whoami)
2. Creating and editing documents with conversational session continuity (/v1/chat)
3. Creating an asynchronous background task (/v1/chat/async) and polling progress (/v1/jobs/{job_id})
4. Exporting the finalized document to styled formats (/v1/documents/export)
"""

import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Load .ENV credentials
load_dotenv()

# Ensure superdocs_langchain package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.toolkit import SuperDocsToolkit


def main():
    print("=" * 70)
    print(" 🚀 SuperDocs API Quickstart: Live Chat & Task Execution")
    print("=" * 70)

    # 1. Initialize Client
    client = SuperDocsClient()
    print(f"• Client Base URL: {client.base_url}")
    print(f"• Mode: {'Offline Mock' if client.offline else 'Live SuperDocs Cloud API'}")

    # 2. Account verification
    whoami = client.get_whoami()
    if whoami.success and whoami.data:
        print(f"• Account Quota: {whoami.data.get('remaining')}/{whoami.data.get('monthly_limit')} ops remaining (Tier: {whoami.data.get('tier')})")
    print("-" * 70)

    session_id = f"quickstart-session-{int(time.time())}"

    # 3. First Chat Request: Create document
    print(f"\n[Step 1] Creating Document via /v1/chat in session '{session_id}'...")
    initial_html = "<h1>Company Security Policy</h1><p>Welcome to the Acme Corp internal security guideline.</p>"
    resp1 = client.chat(
        session_id=session_id,
        message="Add a comprehensive data privacy and compliance section at the end.",
        document_html=initial_html,
    )
    print(f"AI Response: {resp1.message}")
    if resp1.data and resp1.data.get("usage"):
        u = resp1.data["usage"]
        print(f"Usage: {u.get('monthly_used')} used, {u.get('monthly_remaining')} remaining")

    # 4. Multi-turn Follow-up: Edit existing document without re-sending HTML
    print(f"\n[Step 2] Follow-up Turn: Refining the document in the same session...")
    resp2 = client.chat(
        session_id=session_id,
        message="Make the data privacy section more formal and add a table with Data Classification tiers (Public, Internal, Confidential).",
    )
    print(f"AI Response: {resp2.message}")

    # 5. Background Task Creation & Execution (/v1/chat/async + /v1/jobs)
    print(f"\n[Step 3] Creating Async Background Task (/v1/chat/async)...")
    task_session = f"async-task-{int(time.time())}"
    print(f"Dispatching task in session '{task_session}'...")

    def progress_tracker(job_data):
        print(f"   ↳ [Job {job_data.get('job_id')}] Status: {job_data.get('status')} | Progress: {job_data.get('progress', 0)}%")

    task_res = client.execute_task_and_wait(
        session_id=task_session,
        message="Create a Software Architecture Document for a cloud-native microservices platform with an Executive Summary, Component Diagram outline, and Security section.",
        model_tier="core",
        max_wait=120.0,
        progress_callback=progress_tracker,
    )
    print(f"✅ Async Task Completed: {task_res.message}")

    # 6. Export Final Document
    print(f"\n[Step 4] Exporting Final Document (/v1/documents/export)...")
    export_res = client.export_document(
        session_id=session_id,
        export_format="markdown",
    )
    print(f"Export Status: {export_res.message}")

    print("\n" + "=" * 70)
    print(" ✨ Quickstart completed successfully with live SuperDocs API!")
    print("=" * 70)


if __name__ == "__main__":
    main()
