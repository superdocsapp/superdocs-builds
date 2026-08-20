"""Part two. Nothing touches the document until a person says yes.

    export SUPERDOCS_API_KEY=sk_...
    python3 part2_review/review_gate.py                 # asks you about each change
    python3 part2_review/review_gate.py --approve-all    # for a scripted run
    python3 part2_review/review_gate.py --deny-all       # proves denial is real
    python3 part2_review/review_gate.py --revise         # deny once with feedback, let it retry

Costs one operation per document-modifying turn, so a revise run costs two.

Two things this script learned the hard way, both worth knowing before you build
your own gate. A denied change comes back re-proposed, and nothing on the server
caps how many times that can happen: a reviewer that keeps saying no keeps being
asked, and every round is billable. Hence --max-rounds, and hence the rule that
feedback is sent once rather than every time. And the changes in one round are
not independent: approving a renumbering while denying the insertion that caused
it leaves a document numbered for a section that is not there. Judge a round as a
set, not as a list.

Part one made an edit and then checked whether it landed correctly. It had not:
the new section arrived between another section's heading and its own text. That
is the argument for this part. A synchronous edit applies and then you inspect.
This flow proposes, and you inspect first.

The three calls that make it work:

    POST /v1/chat/async         approval_mode="ask_every_time"  -> job_id
    GET  /v1/jobs/{job_id}      status=awaiting_approval, metadata.pending_changes
    POST /v1/chat/{sid}/approve approved=true|false, optional feedback

Every decision is written to out/review-audit.json, because in the workflows that
need an approval gate at all, the record of who allowed what is the point.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from superdocs import Change, SuperDocs, SuperDocsError, Usage, save_export  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample" / "service-agreement.html"
OUT = ROOT / "out"

INSTRUCTION = """Make two changes to this agreement, and nothing else.

1. Insert a new section titled "Confidentiality" immediately after section 3, and renumber the sections that follow it. It says: each party keeps the other's commercial information confidential for three years after the agreement ends; the obligation does not cover information already public or information a party held before disclosure; either party may disclose where a court or regulator requires it, having first told the other party where it is lawful to do so.

2. In the charges table, change the out of hours reactive callout charge from 320 to 360.

Leave every other section, row and formatting detail exactly as it is. Plain contractual English."""

REVISE_FEEDBACK = (
    "This landed inside section 3, between its heading and its own paragraph. "
    "Place the new section after the whole of section 3, including its table, and "
    "leave section 3's own text directly under its heading."
)


def visible_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def show_change(index: int, total: int, change: Change) -> None:
    """Print one proposed change as something a person can actually judge."""
    print("\n" + "=" * 72)
    print(f"change {index} of {total}    chunk {change.chunk_id or 'unknown'}")
    if change.description:
        print(f"the AI says: {change.description[:300]}")
    before, after = visible_text(change.old_html), visible_text(change.new_html)
    if not before and after:
        print("\nthis is new text, nothing is being replaced:\n")
        print("  + " + "\n  + ".join(_wrap(after)))
    elif before and not after:
        print("\nthis deletes existing text:\n")
        print("  - " + "\n  - ".join(_wrap(before)))
    elif before == after:
        # Happens more often than you would expect: the text is identical and the
        # change is a move, a renumbering that came out the same, or formatting.
        print("\nno change to the visible text. This is a position or formatting change.")
        print(f"  text: {before[:120]}")
    else:
        print("\nword level diff, - is going, + is arriving:\n")
        for line in difflib.unified_diff(_wrap(before), _wrap(after), lineterm="", n=1):
            if line.startswith(("---", "+++", "@@")):
                continue
            print("  " + line)
    print("=" * 72)


def _wrap(text: str, width: int = 88) -> list[str]:
    import textwrap

    return textwrap.wrap(text, width=width) or [""]


def ask(index: int, total: int) -> tuple[bool, str]:
    """y approves, n denies, f denies with feedback the AI can revise against."""
    while True:
        answer = input(f"approve change {index}/{total}? [y]es / [n]o / [f]eedback: ").strip().lower()
        if answer in ("y", "yes"):
            return True, ""
        if answer in ("n", "no"):
            return False, ""
        if answer in ("f", "feedback"):
            note = input("what is wrong with it: ").strip()
            return False, note
        print("y, n or f.")


def audit(decisions: list[dict]) -> Path:
    OUT.mkdir(exist_ok=True)
    path = OUT / "review-audit.json"
    path.write_text(json.dumps(decisions, indent=2), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--approve-all", action="store_true", help="approve without asking")
    group.add_argument("--deny-all", action="store_true", help="deny everything, then show the document is untouched")
    group.add_argument("--revise", action="store_true", help="deny the first change with feedback and let the AI retry")
    ap.add_argument("--max-wait", type=float, default=900.0)
    ap.add_argument("--max-rounds", type=int, default=6,
                    help="stop after this many approval rounds. The server has no cap of its own.")
    args = ap.parse_args()

    if not SAMPLE.exists():
        print("Run python3 sample/make_samples.py first.", file=sys.stderr)
        return 2

    client = SuperDocs()
    quota = client.whoami().get("quota", {})
    print(f"operations left: {quota.get('remaining')} of {quota.get('monthly_limit')}")

    original = SAMPLE.read_text(encoding="utf-8")
    session_id = client.init_session()
    print(f"session {session_id}")

    job_id = client.chat_async(
        session_id=session_id,
        message=INSTRUCTION,
        document_html=original,
        approval_mode="ask_every_time",
    )
    print(f"job {job_id} queued, approval gate on\n")

    decisions: list[dict] = []
    seen: set[str] = set()
    rounds = 0

    while True:
        rounds += 1
        job = client.wait_for_job(
            job_id,
            interval=3.0,
            max_wait=args.max_wait,
            on_progress=lambda j: print(f"  status {j.get('status'):<20} progress {j.get('progress')}%"),
        )
        status = job.get("status")
        meta = job.get("metadata") or {}

        if status != "awaiting_approval":
            break

        if rounds > args.max_rounds:
            print(
                f"\nstopping after {args.max_rounds} approval rounds with the job still asking.\n"
                "Every round is a billable turn and the server does not cap them, so the cap\n"
                "lives here. The job stays open; nothing further was approved.",
                file=sys.stderr,
            )
            audit(decisions)
            return 1

        # A pause is not always about a change. A long edit can stop to ask
        # whether to keep going, and that is a different endpoint.
        if meta.get("awaiting_kind") == "continue_prompt":
            print("\nthe edit paused to ask whether to keep going. answering yes.")
            client.continue_job(session_id, job_id, keep_going=True)
            continue

        changes = [c for c in client.pending_changes(job) if c.change_id not in seen]
        if not changes:
            # Nothing new to decide and still awaiting: give the server a moment
            # rather than spinning on it.
            print("  awaiting approval with no new changes listed, waiting")
            time.sleep(3)
            if rounds > args.max_rounds:
                print("still awaiting with nothing to approve. Stopping and leaving the job open.", file=sys.stderr)
                return 1
            continue

        print(f"\n{len(changes)} change(s) waiting for a decision")
        batch: list[dict] = []
        for i, change in enumerate(changes, start=1):
            show_change(i, len(changes), change)
            if args.approve_all:
                approved, note = True, ""
                print("decision: approved (--approve-all)")
            elif args.deny_all:
                approved, note = False, ""
                print("decision: denied (--deny-all)")
            elif args.revise:
                # Feedback goes in once. Denying the same thing every round is how
                # you get twenty six billable retries and a clause that drifts
                # further from what you asked for each time.
                first_pass = rounds == 1 and i == 1
                approved, note = (False, REVISE_FEEDBACK) if first_pass else (True, "")
                print(f"decision: {'denied with feedback' if first_pass else 'approved'} (--revise)")
            else:
                approved, note = ask(i, len(changes))

            seen.add(change.change_id)
            decisions.append(
                {
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "job_id": job_id,
                    "change_id": change.change_id,
                    "chunk_id": change.chunk_id,
                    "approved": approved,
                    "feedback": note,
                    "description": change.description[:300],
                    "old_text": visible_text(change.old_html)[:400],
                    "new_text": visible_text(change.new_html)[:400],
                }
            )
            entry = {"change_id": change.change_id, "approved": approved}
            if note:
                entry["feedback"] = note
            batch.append(entry)

        # One call carries every decision. Approved changes apply atomically,
        # denied ones are discarded, and feedback goes back for a revision.
        if len(batch) == 1:
            only = batch[0]
            client.approve(
                session_id,
                job_id,
                approved=only["approved"],
                change_id=only["change_id"],
                feedback=only.get("feedback"),
            )
        else:
            client.approve(
                session_id,
                job_id,
                approved=any(b["approved"] for b in batch),
                changes=batch,
            )
        print("\ndecisions sent, job resuming")

    print(f"\nfinal status: {status}")
    result = job.get("result") or {}
    usage = Usage.from_response(result.get("usage"))
    if usage.ops_charged:
        print(f"charged {usage.ops_charged} operation(s)")

    changes_block = result.get("document_changes") or {}
    final_html = changes_block.get("updated_html")

    approved_count = sum(1 for d in decisions if d["approved"])
    denied_count = len(decisions) - approved_count
    path = audit(decisions)
    print(f"approved {approved_count}, denied {denied_count}, audit written to {path.relative_to(ROOT)}")

    if not final_html:
        print("no document HTML in the job result. Nothing was written.")
        return 0 if denied_count and not approved_count else 1

    OUT.mkdir(exist_ok=True)
    (OUT / "service-agreement.reviewed.html").write_text(final_html, encoding="utf-8")

    # The check from part one, reused: did the approved edits land where they said?
    sys.path.insert(0, str(ROOT / "part1_first_edit"))
    from first_edit import orphan_headings, sections, number_free  # noqa: E402

    before_sections, after_sections = sections(original), sections(final_html)
    added = [h for h in after_sections if number_free(h) not in {number_free(x) for x in before_sections}]
    print(f"sections added: {added or 'none'}")
    orphans = orphan_headings(final_html)
    print(f"placement: {'clean' if not orphans else f'still wrong under {orphans}'}")

    if "360" in visible_text(final_html):
        print("table: the out of hours charge reads 360, so that change applied")
    elif "320" in visible_text(final_html):
        print("table: the out of hours charge still reads 320, so that change did not apply")

    try:
        payload = client.export(session_id=session_id, fmt="docx", filename="service-agreement.reviewed.docx")
        written = save_export(payload, OUT / "service-agreement.reviewed.docx")
        print(f"wrote out/service-agreement.reviewed.docx ({written / 1024:.1f} KB)")
    except SuperDocsError as exc:
        print(f"export failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nstopped. The job stays open server side; nothing was approved.", file=sys.stderr)
        raise SystemExit(130)
    except SuperDocsError as exc:
        print(f"SuperDocs: {exc}", file=sys.stderr)
        raise SystemExit(1)
