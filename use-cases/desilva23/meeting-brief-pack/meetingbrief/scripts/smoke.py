"""Prove the four calls work against the real API, before building on them.

upload -> chat -> approve -> export, on a deliberately tiny document, so that
a failure here is a failure of the contract rather than of the build.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from superdocs.client import Budget, SuperDocs, SuperDocsError, load_env

ROOT = Path(__file__).resolve().parents[2]
load_env(ROOT / ".env")

SESSION = f"smoke-{int(time.time())}"
RULE = "-" * 70

def step(n, what): print(f"\n{RULE}\n{n}. {what}\n{RULE}")

def main() -> int:
    with SuperDocs(budget=Budget(limit=6)) as sd:
        who = sd.whoami()
        print(f"account {who['account_id'][:8]}… tier={who['tier']} "
              f"remaining={who['quota']['remaining']}")

        step(1, "UPLOAD — load a document as the active editable document")
        src = ROOT / "fixtures" / "smoke-source.md"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(
            "# Weekly Note\n\n## Summary\n\nThe migration is on track.\n\n"
            "## Risks\n\nNone recorded.\n",
            encoding="utf-8",
        )
        up = sd.upload_document(src, SESSION)
        print(f"   uploaded: {list(up)[:8]}")

        step(2, "CHAT — send an edit instruction, pausing for approval")
        job_id = sd.chat_async(
            "Add a short 'Decisions needed' section at the end with one bullet: "
            "confirm the go-live date.",
            SESSION,
            approval_mode="ask_every_time",
        )
        print(f"   job {job_id}")
        job = sd.wait_for_job(
            job_id, what="edit",
            on_tick=lambda s, e: print(f"   … {s} ({e:.0f}s)") if int(e) % 5 == 0 else None,
        )
        print(f"   status: {job.get('status')}")

        step(3, "APPROVE — decide on each proposed change")
        import json as _json
        raw = (job.get("metadata") or {}).get("pending_changes") or []
        print("   raw pending_changes keys: "
              f"{[sorted(r.keys()) for r in raw][:2]}")
        changes = sd.parse_pending_changes(job)
        print(f"   {len(changes)} proposed change(s)")
        for c in changes:
            print(f"   [{c.change_id}] {c.kind}: {c.summary}")
        if changes:
            for c in changes:
                sd.approve(SESSION, job_id, change_id=c.change_id, approved=True)
                print(f"   approved {c.change_id}")
            job = sd.wait_for_job(job_id, what="edit after approval")
            print(f"   status: {job.get('status')}")
        else:
            print("   nothing to approve — the job did not pause")

        step(4, "EXPORT — take the finished file")
        out = sd.export(session_id=SESSION, fmt="docx", out_path=ROOT / "out" / "smoke.docx")
        print(f"   wrote {out} ({out.stat().st_size} bytes)")

        print(f"\n{RULE}\nBUDGET\n{RULE}\n{sd.budget.report()}")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SuperDocsError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        if getattr(exc, "body", None): print(f"body: {exc.body}", file=sys.stderr)
        raise SystemExit(1)
