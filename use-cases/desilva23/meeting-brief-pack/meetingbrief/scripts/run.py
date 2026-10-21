"""Build a meeting brief pack, showing its working as it goes."""
from __future__ import annotations
import argparse, sys, time
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brief import build
from superdocs.client import Budget, SuperDocs, SuperDocsError, load_env

ROOT = Path(__file__).resolve().parents[2]
load_env(ROOT / ".env")
RULE = "─" * 74

def head(t): print(f"\n{RULE}\n{t}\n{RULE}")

def main() -> int:
    ap = argparse.ArgumentParser(description="Calendar and mail to a meeting brief pack")
    ap.add_argument("folder", type=Path, nargs="?",
                    default=ROOT / "fixtures" / "meeting-2026-08-20-trellis")
    ap.add_argument("--today", default="2026-08-14")
    ap.add_argument("--approve-all", action="store_true",
                    help="approve every proposed section (demo only; a person should decide)")
    ap.add_argument("--budget", type=int, default=8)
    ap.add_argument("--format", default="docx")
    ap.add_argument("--tier", default="pro", help="core is unreliable on this instruction; see brief.py")
    args = ap.parse_args()

    session = f"brief-{int(time.time())}"
    with SuperDocs(budget=Budget(limit=args.budget)) as sd:
        def reviewer(change):
            print(f"\n  proposed: {change.summary}")
            return True

        head("1. THE INVITATION — what this meeting actually is")
        result = build(
            args.folder, client=sd, session_id=session,
            today=date.fromisoformat(args.today),
            reviewer=reviewer if args.approve_all else None,
            on_note=lambda m: print(f"\n  note: {m}"),
            out_dir=ROOT / "out", export_format=args.format, model_tier=args.tier,
        )
        m = result.meeting
        print(f"  {m.title}")
        print(f"  {m.when} · {m.location}")
        print(f"  chaired by {m.organiser}")
        for n, e in m.attendees: print(f"    · {n} <{e}>")
        print(f"  agenda: {len(m.agenda)} items")
        for a in m.agenda: print(f"    {a}")

        head("2. WHAT BELONGS IN THIS BRIEF — and what does not")
        for s in sorted(result.sources, key=lambda s: -s.score):
            mark = "KEPT   " if s.selected else "DROPPED"
            print(f"  {mark} {s.score:5.1f}  {s.name}")
            for r in s.reasons: print(f"                  {r}")

        head("3. AT THE GATE — nothing has been applied")
        print(f"  job ended {result.job_status!r} after {result.draft_attempts} draft "
          f"attempt(s); {len(result.changes)} proposed section(s)")
        for c in result.changes:
            print(f"    [{c.change_id[:8]}] {c.summary}")
        if result.approved:
            print(f"\n  approved {len(result.approved)}, rejected {len(result.rejected)}")
        else:
            print("\n  waiting for a human. Re-run with --approve-all to apply them.")

        if result.exported:
            head("4. EXPORTED")
            print(f"  {result.exported} ({result.exported.stat().st_size} bytes)")
            if result.unfilled_sections:
                print("\n  INCOMPLETE — these sections were never filled:")
                for h in result.unfilled_sections:
                    print(f"    · {h}")
                print("  The file was still written, but it is not a finished brief "
                      "and is not described as one.")
            else:
                print("  every section was filled and reviewed")

        head("WHAT THIS COST")
        print(sd.budget.report())
        print(f"\n  {len([s for s in result.sources if s.selected])} of "
              f"{len(result.sources)} candidate sources were sent to the model.")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SuperDocsError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr); raise SystemExit(1)
