#!/usr/bin/env python3
"""Minimal isolated SuperDocs operation — fast diagnostic for single-fact
gate behavior. Runs ONE fact through the production path:

  template upload → build_section_operations → chat_async(ask_every_time)
  → pending_changes (chunk_id, old/new html, ai_explanation)
  → validator decision → approve/deny → final HTML

Run:  python benchmarks/minimal_op.py "<fact text>" [--section Section Name]

No full audio; completes in ~1-2 minutes.
"""

import argparse
import asyncio
import base64
import json
import sys
import time

import os
# Resolved from this file, not hardcoded. The absolute path that used to be
# here pointed at a folder name that no longer exists, so this script could
# not run on any machine, including the one it was written on.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from app.core.config import get_settings
from app.drafting.classifier import ADDITION, build_section_operations
from app.drafting.templates import render_template, SOW
from app.drafting.validator import validate_proposal
from app.superdocs.client import SuperDocsClient

POLL_INTERVAL = 2.0
POLL_DEADLINE = 180.0


async def poll_job(client, job_id, statuses):
    deadline = time.monotonic() + POLL_DEADLINE
    while time.monotonic() < deadline:
        job = await client.get_job(job_id)
        if job.status in statuses:
            return job
        await asyncio.sleep(POLL_INTERVAL)
    return None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fact", help="the fact text to test")
    ap.add_argument("--section", default=None, help="force target section (optional)")
    args = ap.parse_args()

    settings = get_settings()
    client = SuperDocsClient(api_key=settings.superdocs_api_key)
    template = render_template(SOW, date="August 12, 2026")

    try:
        upload = await client.upload_base64(
            file_base64=base64.b64encode(template.encode()).decode(),
            filename="draft.html",
            session_id=f"minop-{int(time.time())}",
            return_html=True,
        )
        sid = upload.session_id
        draft = upload.html or template

        ops = build_section_operations(ADDITION, args.fact, draft, SOW)
        if not ops:
            print("NO OPERATIONS — fact filtered as meaningless/filler")
            return
        op = ops[0]
        print(f"=== FACT: {args.fact!r}")
        print(f"CLASSIFIER TARGET: {op.section!r}")
        print(f"=== INSTRUCTION (first 300 chars) ===")
        print(op.instruction[:300])
        print("...")
        print(f"EXPECTED FACTS: {op.facts}")

        job = await client.chat_async(
            message=op.instruction, session_id=sid, approval_mode="ask_every_time"
        )
        settled = await poll_job(client, job.job_id, ("awaiting_approval", "completed", "failed"))
        if settled is None or settled.status != "awaiting_approval":
            print(f"JOB STATUS: {settled.status if settled else 'timeout'}")
            return
        print("\n=== PROPOSAL (pending_changes) ===")
        for c in settled.metadata.pending_changes:
            print(f"  change_id={c.change_id}")
            print(f"  operation={c.operation} chunk_id={c.chunk_id}")
            print(f"  old_html={str(c.old_html)[:200]!r}")
            print(f"  new_html={str(c.new_html)[:250]!r}")
            print(f"  ai_explanation={str(c.ai_explanation)[:200]!r}")
            ok, fails = validate_proposal(op, c, draft)
            print(f"  VALIDATOR: {'PASS' if ok else 'FAIL'} {fails}")

        # Approve and show final html
        await client.approve_changes(
            session_id=sid,
            job_id=job.job_id,
            approved=True,
            changes=[{"change_id": c.change_id, "approved": True} for c in settled.metadata.pending_changes],
        )
        final = await poll_job(client, job.job_id, ("completed", "failed"))
        if final and final.document_changes:
            print("\n=== FINAL DOCUMENT (after approve) ===")
            print(final.document_changes.updated_html)
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
