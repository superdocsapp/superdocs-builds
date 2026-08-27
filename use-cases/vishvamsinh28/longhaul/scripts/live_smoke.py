"""Confirm the four-call contract against the real SuperDocs API.

Everything else in this repository runs offline against a deterministic stand-in. This
script is the one thing that talks to api.superdocs.app, and it exists so the contract
Longhaul is built on can be checked against the real service rather than assumed.

It is deliberately the smallest useful run: one tiny synthetic document, one edit
instruction, one approval, two exports. That is **one billable operation** — exports and
reads cost nothing. Nothing here loops, and nothing scales with corpus size.

    cp .env.example .env      # then put your key in it
    uv run python scripts/live_smoke.py

Add --keep to leave the session in place if you want to look at it in the web app.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from longhaul.client import SuperDocsClient, SuperDocsError  # noqa: E402
from longhaul.config import load_settings  # noqa: E402
from longhaul.model import step_token  # noqa: E402
from longhaul.runner import _proposals_from  # noqa: E402  (deliberate: the smoke
# test must exercise exactly the parsing the runner uses, not a second copy of it)

DOCUMENT = """# Northwind Systems — On-Call Note

This is a synthetic document created to smoke-test an API integration. It describes a
company that does not exist and contains nothing confidential.

All alerts route through PagerDuty. The on-call engineer acknowledges there first.

Escalation goes to the Ops Lead after fifteen minutes.
"""

STEPS = (
    "Throughout this note, replace \"PagerDuty\" with \"Rootly\", "
    "leaving every other detail untouched."
)


def check(label: str, ok: bool, detail: str = "") -> bool:
    mark = "\033[32m  ok\033[0m" if ok else "\033[31mFAIL\033[0m"
    print(f"{mark}  {label}" + (f"\n      {detail}" if detail else ""))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true",
                        help="Leave the session in place to inspect in the web app.")
    args = parser.parse_args()

    settings = load_settings()
    print(f"base url : {settings.base_url}")
    print(f"api key  : {settings.redacted()}\n")
    if not settings.api_key:
        print("No API key. Copy .env.example to .env and put your key in it.")
        print("Get one from use.superdocs.app -> Settings -> API Keys.")
        return 2

    session_id = f"longhaul-smoke-{uuid.uuid4().hex[:8]}"
    token = step_token(session_id, 0)
    scratch = ROOT / ".smoke"
    scratch.mkdir(exist_ok=True)
    source = scratch / "oncall-note.md"
    source.write_text(DOCUMENT, encoding="utf-8")

    passed = True
    try:
        with SuperDocsClient(settings.api_key, settings.base_url, timeout=300) as client:
            passed &= check("key accepted (GET /v1/sessions, costs nothing)", client.ping())

            # 1. upload
            upload = client.upload_document(session_id, source, open_mode="background")
            passed &= check(
                "1/4 upload — POST /v1/documents/upload",
                bool(upload.document_id) and bool(upload.html),
                f"document_id={upload.document_id} chunks={upload.chunks_count}",
            )

            # 2. chat, in review mode so the approval gate is exercised
            started = time.monotonic()
            job_id = client.chat_async(
                session_id, f"{STEPS} {token}",
                document_id=upload.document_id, approval_mode="ask_every_time",
            )
            passed &= check("2/4 chat — POST /v1/chat/async", bool(job_id), f"job_id={job_id}")

            print("      waiting for the model. A turn can take from thirty seconds to "
                  "several\n      minutes with no visible progress; that is still processing.")
            job = client.wait_for_job(
                job_id, until=frozenset({"awaiting_approval", "completed"}), max_wait=900,
                on_wait=lambda _j: None,
            )
            elapsed = time.monotonic() - started
            passed &= check(f"     job settled after {elapsed:.0f}s",
                            job.status in ("awaiting_approval", "completed"),
                            f"status={job.status} awaiting_kind={job.awaiting_kind}")

            # The documented trap: proposed-change content arrives JSON-encoded inside
            # JSON. If the second parse is missing, every field here reads as None.
            proposals = _proposals_from("smoke", 0, job, upload.document_id)
            parsed_ok = all(p.change_id and (p.new_html or p.operation == "delete")
                            for p in proposals)
            passed &= check(
                f"     proposed changes parsed ({len(proposals)})",
                bool(proposals) and parsed_ok,
                "\n      ".join(f"{p.operation} {p.change_id}: {p.ai_explanation[:70]}"
                                for p in proposals[:3]) or "no changes proposed",
            )

            # 3. approve — the human gate, item by item
            if job.status == "awaiting_approval" and proposals:
                client.approve(
                    session_id, job_id,
                    [(p.change_id, True, None) for p in proposals],
                )
                job = client.wait_for_job(job_id, until=frozenset({"completed"}), max_wait=900)
                passed &= check("3/4 approve — POST /v1/chat/{session}/approve",
                                job.status == "completed", f"status={job.status}")
            else:
                check("3/4 approve — skipped", True,
                      "the turn did not pause for review, so there was nothing to approve")

            # 4. export
            md = client.export(session_id=session_id, document_id=upload.document_id,
                               fmt="markdown")
            docx = client.export(session_id=session_id, document_id=upload.document_id,
                                 fmt="docx")
            (scratch / "result.md").write_bytes(md)
            (scratch / "result.docx").write_bytes(docx)
            passed &= check(
                "4/4 export — POST /v1/documents/export (costs no operations)",
                bool(md) and bool(docx),
                f"markdown {len(md)} bytes, docx {len(docx)} bytes -> .smoke/",
            )

            # The edit actually landed.
            text = md.decode("utf-8", errors="replace")
            passed &= check("the edit is in the exported document",
                            "Rootly" in text, f"'Rootly' present: {'Rootly' in text}")

            # Reconciliation depends on both of these surviving; check they really do.
            history = client.session_history(session_id, include_document_html=False)
            messages = history.get("messages", []) or []
            passed &= check(
                "the idempotency token is in the session transcript",
                any(token in (m.get("content") or "") for m in messages),
                "this is what lets a crashed run ask the server whether a turn happened",
            )
            roster = client.session_documents(session_id)
            passed &= check("the session roster lists the document",
                            any(d.get("document_id") == upload.document_id for d in roster))

            usage = (job.result or {}).get("usage") or {}
            if usage:
                print(f"\noperations: {usage.get('monthly_used')} used of "
                      f"{usage.get('monthly_limit')} "
                      f"({usage.get('monthly_remaining')} remaining). "
                      f"This run cost 1.")
    except SuperDocsError as exc:
        print(f"\n\033[31m{exc}\033[0m")
        return 1

    if not args.keep:
        print(f"\nsession {session_id} left on the server "
              "(sessions cannot be deleted with an API key; stop reusing the id to retire it)")

    print()
    if passed:
        print("\033[32mThe four-call contract works against the live API.\033[0m")
        return 0
    print("\033[31mSomething in the contract did not hold. Details above.\033[0m")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
