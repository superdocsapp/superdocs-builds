"""Live SuperDocs smoke test — uses SUPERDOCS_API_KEY from .env (never printed).

Exercises the four-call contract against the real API with a tiny synthetic
document. Run from the project root after copying .env.example -> .env:

    python scripts/live_smoke.py

Optional flags:
    --skip-edit     upload + export only (saves one billable op)
    --skip-export   upload + edit poll only
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import uuid
from pathlib import Path

# Ensure project root is importable when run as a script.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.integrations.superdocs.client import SuperDocsClient  # noqa: E402
from app.integrations.superdocs.exceptions import SuperDocsError  # noqa: E402

_PLACEHOLDER_KEYS = {
    "",
    "mock-key-for-local",
    "your-superdocs-key-here",
    "unused-because-mocked",
}


async def _poll_job(client: SuperDocsClient, job_id: str, *, label: str) -> dict:
    print(f"  polling {label} job {job_id} ...")
    for attempt in range(1, 91):  # up to ~3 minutes
        job = await client.get_job(job_id)
        print(f"    [{attempt}] status={job.status} ops={job.ops_cost}")
        if job.status in {"completed", "failed", "cancelled", "awaiting_approval"}:
            return job.raw
        await asyncio.sleep(2)
    raise TimeoutError(f"{label} job {job_id} did not finish in time")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-edit", action="store_true")
    parser.add_argument("--skip-export", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    key = settings.superdocs_api_key.strip()
    if key in _PLACEHOLDER_KEYS:
        print("ERROR: Set a real SUPERDOCS_API_KEY in .env before running this script.")
        return 1

    client = SuperDocsClient(
        base_url=settings.superdocs_base_url,
        api_key=key,
        timeout_seconds=120.0,
    )

    session_id = uuid.uuid4().hex
    tmp = Path(tempfile.mkdtemp(prefix="tdg_live_"))
    doc_path = tmp / "smoke_test.txt"
    doc_path.write_text(
        "SMOKE TEST DOCUMENT\n\nSection 1: This is synthetic fictional content.\n",
        encoding="utf-8",
    )

    try:
        print("1) UPLOAD  POST /v1/documents/upload")
        uploaded = await client.upload_document(
            file_path=str(doc_path),
            filename="smoke_test.txt",
            content_type="text/plain",
            session_id=session_id,
        )
        print(f"   session_id={uploaded.session_id} document_id={uploaded.document_id}")

        edit_job_id: str | None = None
        if not args.skip_edit:
            print("2) EDIT    POST /v1/chat/async")
            started = await client.start_chat_async(
                session_id=uploaded.session_id,
                instruction="Add a short bullet list with two items under Section 1.",
                approval_mode="ask_every_time",
                model_tier="core",
            )
            edit_job_id = started.job_id
            print(f"   job_id={edit_job_id}")
            raw = await _poll_job(client, edit_job_id, label="edit")
            metadata = raw.get("metadata") or {}
            pending = client.parse_changes(metadata.get("pending_changes"))
            print(f"   pending_changes={len(pending)}")
            if pending:
                first = pending[0]
                change_id = str(first.get("change_id") or "")
                print("3) APPROVE POST /v1/chat/{session_id}/approve (first change only)")
                await client.decide_change(
                    session_id=uploaded.session_id,
                    job_id=edit_job_id,
                    change_id=change_id,
                    approved=True,
                )
                print(f"   approved change_id={change_id}")

        if not args.skip_export:
            step = 4 if not args.skip_edit else 2
            print(f"{step}) EXPORT  POST /v1/documents/export")
            exported = await client.export_document(session_id=uploaded.session_id, fmt="txt")
            print(
                "   download_url="
                f"{'yes' if exported.download_url else 'no'} "
                f"inline={'yes' if exported.inline_content else 'no'}"
            )

        print("\nOK — live SuperDocs smoke test completed.")
        return 0
    except SuperDocsError as exc:
        print(f"\nFAIL — SuperDocs API error: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAIL — {type(exc).__name__}: {exc}")
        return 3
    finally:
        await client.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
