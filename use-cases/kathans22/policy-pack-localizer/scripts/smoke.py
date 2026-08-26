"""End-to-end smoke test: upload, edit, approve, export, and print the cost ledger."""

from __future__ import annotations

import asyncio
import base64
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from localizer.ledger import Ledger, ops_from_response
from localizer.mcp_client import SuperDocsClient, SuperDocsClientError, parse_proposed_changes

ROOT = Path(__file__).resolve().parents[1]
POLICY_MASTER = ROOT / "config" / "policy-master.md"
SESSION_ID = "smoke-test-1"
EDIT_INSTRUCTION = (
    'In section 6 "Reporting Channels" only, replace the two generic placeholder '
    "lines with this India office content: internal contact is the Country "
    "Safeguarding Focal Point, Mumbai, reachable at "
    "safeguarding.in@meridian-relief.example or +91 22 0000 0000; external channels "
    "are Childline India (1098, toll-free 24-hour child helpline) and the Police "
    "Control Room (112). Do not touch any other section."
)


def _extract_section(markdown: str, number: int) -> str:
    match = re.search(rf"^## {number} .+?\n(.*?)(?=\n## |\Z)", markdown, re.S | re.M)
    return match.group(0).strip() if match else "(section not found in export)"


async def run() -> None:
    ledger = Ledger()
    file_base64 = base64.b64encode(POLICY_MASTER.read_bytes()).decode("ascii")

    async with SuperDocsClient() as client:
        started = time.monotonic()
        await client.upload(filename="policy-master.md", file_base64=file_base64, session_id=SESSION_ID)
        ledger.record("upload", "policy-master.md", chat_calls=0, wall_time=time.monotonic() - started)

        # Preview the change first, so it can be parsed and inspected before anything applies.
        started = time.monotonic()
        review_response = await client.chat(
            message=EDIT_INSTRUCTION, session_id=SESSION_ID,
            approval_mode="ask_every_time", response_mode="compact",
        )
        ledger.record(
            "chat", "section 6 edit (preview)",
            chat_calls=ops_from_response(review_response), wall_time=time.monotonic() - started,
        )

        changes = parse_proposed_changes(review_response)
        change = changes[0]
        print(f"Proposed change {change['change_id']} on chunk {change['chunk_id']}:")
        print(change["new_html"])
        print()

        # Known limitation (see PROGRESS.md): approve_change requires a job_id
        # from chat_async; a synchronous chat() preview never creates one, so
        # this is expected to fail against SuperDocs today. Call it anyway —
        # a smoke test's job is to show what actually happens, not what should.
        started = time.monotonic()
        try:
            await client.approve(
                session_id=SESSION_ID, job_id=SESSION_ID,
                change_id=change["change_id"], approved=True,
            )
            ledger.record("approve", change["change_id"], chat_calls=0, wall_time=time.monotonic() - started)
        except SuperDocsClientError as exc:
            ledger.record(
                "approve", f"{change['change_id']} (failed, see PROGRESS.md)",
                chat_calls=0, wall_time=time.monotonic() - started,
            )
            print(f"approve() failed as documented in PROGRESS.md: {exc}")
            print("Falling back to a second chat call with the default approval_mode "
                  "(approve_all) so the edit is actually applied.\n")
            started = time.monotonic()
            apply_response = await client.chat(
                message=EDIT_INSTRUCTION, session_id=SESSION_ID, response_mode="compact"
            )
            ledger.record(
                "chat", "section 6 edit (apply)",
                chat_calls=ops_from_response(apply_response), wall_time=time.monotonic() - started,
            )

        started = time.monotonic()
        export_response = await client.export(session_id=SESSION_ID, format="markdown")
        ledger.record("export", "markdown", chat_calls=0, wall_time=time.monotonic() - started)

    ledger.report()

    markdown = export_response.get("text") or export_response.get("markdown") or export_response.get("content")
    if markdown:
        print("\n--- Section 6 (exported) ---")
        print(_extract_section(markdown, 6))


if __name__ == "__main__":
    asyncio.run(run())
