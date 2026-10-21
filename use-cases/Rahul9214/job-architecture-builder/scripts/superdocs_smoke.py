"""Manual SuperDocs live smoke. Not collected by pytest. Do not run unless asked.

Requires SUPERDOCS_API_KEY. Uploads a tiny synthetic fixture, starts a reviewed
edit, and stops at human approval unless --decide is passed. Export runs only
after an explicit decision or if the job already completed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from html import escape

from job_architecture.superdocs.client import SuperDocsClient
from job_architecture.superdocs.config import load_settings
from job_architecture.superdocs.errors import ConfigurationError, JobFailedError, JobTimeoutError
from job_architecture.superdocs.models import ExportRequest, ReviewDecision

FIXTURE = ROOT / "fixtures" / "superdocs" / "smoke-role.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manual SuperDocs reviewed-edit smoke")
    parser.add_argument("--session-id", default="job-arch-smoke")
    parser.add_argument("--message", default="Add a one-line review note at the end of the document.")
    parser.add_argument(
        "--decide",
        choices=("approve", "reject"),
        default=None,
        help="Optional explicit decision. Omitted: stop at awaiting_approval and do not approve.",
    )
    parser.add_argument("--export", type=Path, default=None, help="Write export bytes here after a decision.")
    parser.add_argument("--max-wait-seconds", type=float, default=180.0)
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(exc, file=sys.stderr)
        return 2

    if not FIXTURE.exists():
        print(f"Missing fixture: {FIXTURE}", file=sys.stderr)
        return 2

    with SuperDocsClient(settings) as client:
        uploaded = client.upload_document(
            FIXTURE.name,
            FIXTURE.read_bytes(),
            session_id=args.session_id,
            open_mode="new_focused",
            operation_key="smoke-upload",
        )
        print(f"uploaded document_id={uploaded.document.document_id} session={uploaded.session_id}")
        handle = client.start_reviewed_edit(
            args.session_id,
            args.message,
            document_id=uploaded.document.document_id,
            operation_key="smoke-edit",
        )
        print(f"job {handle.job_id} accepted status={handle.normalized_status}")
        try:
            snapshot = client.wait_for_job(
                handle.job_id,
                max_wait_seconds=args.max_wait_seconds,
                stop_on_review=True,
            )
        except (JobTimeoutError, JobFailedError) as exc:
            print(exc, file=sys.stderr)
            return 1

        print(f"job status={snapshot.status} awaiting_kind={snapshot.awaiting_kind}")
        if snapshot.status == "awaiting_approval" and snapshot.awaiting_kind == "continue_prompt":
            print("Large-edit continue_prompt received. Smoke stops without auto-continuing.")
            return 0
        if snapshot.status == "awaiting_approval":
            for change in snapshot.pending_changes:
                print(
                    f"proposed {change.change_id} op={change.operation} "
                    f"before={change.before!r} after={change.after!r} reason={change.reason!r}"
                )
            if args.decide is None:
                print("Stopping at human approval. Re-run with --decide approve|reject to continue.")
                return 0
            decisions = [
                ReviewDecision(change_id=change.change_id, approved=args.decide == "approve")
                for change in snapshot.pending_changes
            ]
            if not decisions:
                print("No pending changes to decide.", file=sys.stderr)
                return 1
            result = client.submit_review(args.session_id, snapshot.job_id, decisions)
            print(f"submitted {len(result.decided)} explicit decision(s) all_approved={result.all_approved}")
            snapshot = client.wait_for_job(snapshot.job_id, max_wait_seconds=args.max_wait_seconds)

        if args.export is None:
            print(f"done status={snapshot.status}; pass --export PATH to download bytes")
            return 0
        exported = client.export_document(
            args.export,
            ExportRequest(
                session_id=args.session_id,
                html=f"<h1>Smoke role</h1><pre>{escape(FIXTURE.read_text(encoding='utf-8'))}</pre>",
                format="docx",
                filename=args.export.name,
            ),
        )
        print(f"exported {exported.byte_count} bytes to {exported.destination}")
        return 0


if __name__ == "__main__":
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise SystemExit("Live SuperDocs smoke must not run under pytest")
    raise SystemExit(main())
