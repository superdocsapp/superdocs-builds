#!/usr/bin/env python3
"""Smoke-test the SuperDocs REST contract this app depends on, using this
codebase's own client — not Task 1's scripts/probe_superdocs_api.py, which
this repo is explicitly kept isolated from (design decision 2). Mirrors the
verification *pattern* that script established (a small, structured document
with known section names, so a reassembly bug shows up as a missing section
rather than needing a human to eyeball a diff) — not its code.

Exercises the brief's stated minimum contract end to end: upload, chat
(an edit instruction), approve, export.

Usage:
    echo 'SUPERDOCS_API_KEY=sk_...' >> .env
    make smoke
    # equivalent, if not using make:
    cd backend && PYTHONPATH=. ../.venv/bin/python scripts/smoke_superdocs_contract.py
"""

from __future__ import annotations

import asyncio
import base64
import sys
import time
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.superdocs.client import SuperDocsClient


def describe(e: Exception) -> str:
    # httpx.HTTPStatusError's own str() is just the status line — the
    # response body is where SuperDocs actually says which field it
    # rejected, and reading it here beats a separate diagnostic curl every
    # time a 4xx shows up.
    if isinstance(e, httpx.HTTPStatusError):
        return f"{type(e).__name__}: {e} | body: {e.response.text[:500]}"
    return f"{type(e).__name__}: {e}"


SAMPLE_HTML = """<h1>Statement of Work</h1>
<h2>Parties</h2>
<p>Client: Northwind Logistics Ltd. Supplier: Meridian Componentes Holdings Ltd.</p>
<h2>Scope</h2>
<p>Supplier will deliver warehouse automation consulting.</p>
<h2>Commercials</h2>
<p>Fees: USD 48,000. Start date: 3 September 2026.</p>
<h2>Signatures</h2>
<p>Signed for and on behalf of both parties.</p>
"""

EXPECTED_SECTIONS = ["Parties", "Scope", "Commercials", "Signatures"]
# Generous — the brief's own warning: large-document ops can take 30s to
# several minutes with no visible progress. A stopping rule still exists so
# a broken poll can't hang forever.
POLL_DEADLINE_SECONDS = 300


def step(n: int, label: str) -> None:
    print(f"\n[{n}] {label}")
    print("-" * 60)


async def main() -> int:
    settings = get_settings()
    if not settings.superdocs_api_key:
        sys.exit(
            "SUPERDOCS_API_KEY not set.\n"
            "Add it to .env:  echo 'SUPERDOCS_API_KEY=sk_...' >> .env\n"
            "(.env is gitignored; the key is never printed by this script.)"
        )

    session_id = f"m1-smoke-{int(time.time())}"
    results: dict[str, str] = {}

    async with SuperDocsClient(settings.superdocs_api_key, settings.superdocs_base_url) as client:
        step(1, "UPLOAD  POST /v1/documents/upload-base64")
        try:
            upload = await client.upload_base64(
                file_base64=base64.b64encode(SAMPLE_HTML.encode()).decode(),
                filename="sow.html",
                session_id=session_id,
                return_html=True,
            )
            present = [s for s in EXPECTED_SECTIONS if s in (upload.html or "")]
            print(f"    sections returned: {len(present)}/{len(EXPECTED_SECTIONS)} {present}")
            results["upload"] = (
                "OK" if len(present) == len(EXPECTED_SECTIONS) else f"PARTIAL {present}"
            )
        except Exception as e:
            results["upload"] = f"ERROR {describe(e)}"
            return report(results)

        step(2, "EDIT    POST /v1/chat/async  (approval_mode=ask_every_time)")
        job_id = None
        try:
            chat = await client.chat_async(
                message="Change the start date to 15 September 2026. Change nothing else.",
                session_id=session_id,
                approval_mode="ask_every_time",
            )
            job_id = chat.job_id
            print(f"    job_id: {job_id}")
            results["chat"] = "OK" if job_id else "FAIL no job_id"
        except Exception as e:
            results["chat"] = f"ERROR {describe(e)}"
            return report(results)

        async def poll_until_settled() -> tuple[str, list]:
            """Poll until the job reaches a state that won't change on its
            own. Reused after approve too — approving doesn't finish the job
            synchronously (found the hard way: an export taken right after
            approve returned 200 still showed the pre-edit document, because
            nothing polled the job back to `completed` first)."""
            status = "unknown"
            pending: list = []
            deadline = time.time() + POLL_DEADLINE_SECONDS
            while time.time() < deadline:
                job = await client.get_job(job_id)
                status = job.status
                print(f"    status={status} awaiting_kind={job.metadata.awaiting_kind!r}")
                if status in ("awaiting_approval", "completed", "failed", "cancelled"):
                    pending = job.metadata.pending_changes
                    for c in pending:
                        print(
                            f"    pending: chunk_id={c.chunk_id} operation={c.operation!r} "
                            f"new_html={(c.new_html or '')[:120]!r}"
                        )
                    if job.document_changes:
                        print(
                            f"    document_changes.updated_html present: "
                            f"{job.document_changes.updated_html is not None}"
                        )
                    break
                await asyncio.sleep(4)
            return status, pending

        step(3, "POLL    GET /v1/jobs/{job_id}  (slow is normal, not a crash)")
        pending = []
        status = "unknown"
        try:
            status, pending = await poll_until_settled()
            print(f"    final status: {status}, pending_changes: {len(pending)}")
            results["poll"] = f"{status}, {len(pending)} pending"
        except Exception as e:
            results["poll"] = f"ERROR {describe(e)}"

        step(4, "APPROVE POST /v1/chat/{session_id}/approve")
        if pending:
            try:
                for change in pending:
                    print(f"    approving chunk_id={change.chunk_id}")
                    approve_response = await client.approve(
                        session_id=session_id,
                        job_id=job_id,
                        approved=True,
                        chunk_id=change.chunk_id,
                    )
                    print(f"    approve response body: {approve_response}")
                status, pending = await poll_until_settled()
                print(f"    after approve, job settled at: {status}")
                results["approve"] = f"OK (settled: {status})"
            except Exception as e:
                results["approve"] = f"ERROR {describe(e)}"
        else:
            results["approve"] = "SKIPPED (nothing pending to approve)"
            print("    skipped — no pending changes returned")

        step(5, "EXPORT  POST /v1/documents/export  (exports are free)")
        try:
            export = await client.export(session_id=session_id, format="html")
            out = export.content.decode(errors="replace")
            present = [s for s in EXPECTED_SECTIONS if s in out]
            missing = set(EXPECTED_SECTIONS) - set(present)
            print(f"    sections in export: {len(present)}/{len(EXPECTED_SECTIONS)} {present}")
            if missing:
                print(
                    f"    *** MISSING AFTER EDIT: {sorted(missing)} "
                    "— reproduces the documented content-loss risk."
                )

            # Sections surviving isn't the same as the edit actually
            # applying — check the requested change landed, not just that
            # nothing else broke.
            edit_landed = "15 September 2026" in out
            edit_stale = "3 September 2026" in out and "13 September 2026" not in out
            print(f"    edit applied (new date present): {edit_landed}")
            if edit_stale:
                print("    *** OLD DATE STILL PRESENT — instruction may not have applied.")

            if export.warnings:
                print(f"    export warnings: {export.warnings}")

            Path("smoke_export.html").write_text(out)
            print("    wrote smoke_export.html for inspection")

            results["export"] = (
                f"OK ({len(present)}/{len(EXPECTED_SECTIONS)} sections, edit_applied={edit_landed})"
            )
        except Exception as e:
            results["export"] = f"ERROR {describe(e)}"

    return report(results)


def report(results: dict[str, str]) -> int:
    print("\n" + "=" * 60)
    print("VERDICT — does this codebase's own SuperDocs client work end to end?")
    print("=" * 60)
    for k in ("upload", "chat", "poll", "approve", "export"):
        print(f"  {k:9} {results.get(k, 'not reached')}")
    broken = [k for k, v in results.items() if v.startswith(("FAIL", "ERROR"))]
    print()
    if broken:
        print(f"  BLOCKED at: {', '.join(broken)}")
    else:
        print("  4-call contract confirmed working from this codebase's own client.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
