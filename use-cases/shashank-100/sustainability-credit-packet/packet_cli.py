"""Command line interface: build a packet, review changes, export the bundle.

The review command is the human gate. Proposed changes are shown one at a time
with their before and after, and each is accepted or rejected on its own --
rejecting one never discards the rest.
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from pathlib import Path

import client
import packet as packet_mod
import registry

HERE = Path(__file__).parent


def _plain(html: str, limit: int | None = None) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + "..."
    return text


def _print_scorecard(score: registry.Scorecard) -> None:
    print(f"\n{score.project['name']}")
    print(f"{score.project['rating_system']}")
    print("-" * 72)
    for credit in score.credits:
        flag = " " if credit.status == registry.DOCUMENTED else "!"
        print(
            f" {flag} {credit.id:6} {credit.status:20} "
            f"{credit.points_awarded:2} of {credit.result.points:2} pts   {credit.name}"
        )
        for item in credit.missing_evidence:
            print(f"        missing: {item.file}")
    print("-" * 72)
    print(f"   Claimed {score.points_awarded} of {score.points_targeted} targeted -> {score.level}")
    if not score.meets_target:
        print(f"   {score.shortfall_to_target} points short of {score.target_level}")
    print()


def cmd_status(args) -> int:
    _print_scorecard(registry.load(HERE / "credits.yaml", root=HERE))
    return 0


def cmd_build(args) -> int:
    score = registry.load(HERE / "credits.yaml", root=HERE)
    session = args.session or f"packet-{uuid.uuid4().hex[:8]}"
    pk = packet_mod.Packet(score, session_prefix=session, budget=args.budget)

    credits = [c for c in score.credits if not args.credit or c.id in args.credit]
    if not credits:
        print(f"No credit matching {args.credit}", file=sys.stderr)
        return 2

    print(f"session {session}")
    for credit in credits:
        print(f"\n{credit.id} {credit.name}")
        pk.attach_sources(credit)
        if pk.unattached:
            for note in pk.unattached:
                print(f"  could not attach: {note}")
        pk.build_narrative(credit, approve=not args.review)
        print(f"  {pk.gated} section(s) gated for review")

    if args.review:
        print(f"\n{len(pk.pending)} section(s) awaiting your decision.")
        print(f"Review them with:  packet_cli review --session {session}")
    else:
        problems = pk.verify()
        if problems:
            print("\nProblems found:")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print("\nNo problems found.")

    print()
    print(pk.sd.usage.report())
    return 0


def cmd_review(args) -> int:
    """Walk the queued changes and decide each one."""
    sd = client.SuperDocs()
    jobs = sd._call("GET", "/v1/jobs", stage="review:list")
    queue = [
        job for job in (jobs.get("jobs") if isinstance(jobs, dict) else jobs) or []
        if isinstance(job, dict)
        and job.get("session_id") == args.session
        and job.get("status") == "awaiting_approval"
    ]

    if not queue:
        print(f"Nothing awaiting review in session {args.session}.")
        return 0

    for job in queue:
        changes = sd.changes_from(job)
        if not changes:
            continue
        print(f"\njob {job['job_id'][:8]} -- {len(changes)} proposed change(s)")

        decisions = []
        for index, change in enumerate(changes, 1):
            print(f"\n  [{index}/{len(changes)}] {change.operation}", end="")
            if change.document_id:
                print(f" in {change.document_id}", end="")
            print()
            if change.old_html:
                print(f"      before: {_plain(change.old_html, 300)}")
            print(f"      after:  {_plain(change.new_html, 300)}")
            if change.explanation:
                print(f"      why:    {_plain(change.explanation, 160)}")

            if args.approve_all:
                verdict = True
            elif args.reject_all:
                verdict = False
            else:
                answer = input("      approve? [y/N] ").strip().lower()
                verdict = answer in ("y", "yes")
            decisions.append({"change_id": change.change_id, "approved": verdict})
            print(f"      -> {'approved' if verdict else 'rejected'}")

        sd.approve(args.session, decisions, job_id=job["job_id"])
        sd.wait_until_idle(args.session)
        kept = sum(1 for d in decisions if d["approved"])
        print(f"\n  applied: {kept} approved, {len(decisions) - kept} rejected")

    return 0


def cmd_export(args) -> int:
    sd = client.SuperDocs()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(sd.export(args.session, args.format))
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="packet_cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show the credit register and scorecard").set_defaults(
        func=cmd_status
    )

    build = sub.add_parser("build", help="build packet sections through SuperDocs")
    build.add_argument("--credit", action="append", help="credit id, repeatable")
    build.add_argument("--session", help="session id (default: generated)")
    build.add_argument("--budget", type=int, default=packet_mod.DEFAULT_BUDGET,
                       help="operation ceiling for this run")
    build.add_argument("--review", action="store_true",
                       help="queue changes for review instead of approving them")
    build.set_defaults(func=cmd_build)

    review = sub.add_parser("review", help="approve or reject queued changes")
    review.add_argument("--session", required=True)
    review.add_argument("--approve-all", action="store_true")
    review.add_argument("--reject-all", action="store_true")
    review.set_defaults(func=cmd_review)

    export = sub.add_parser("export", help="export the session's document")
    export.add_argument("--session", required=True)
    export.add_argument("--format", default="docx",
                        choices=["docx", "pdf", "html", "markdown", "txt"])
    export.add_argument("--out", default="out/packet.docx")
    export.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except client.QuotaExhausted as exc:
        print(f"\nStopped: {exc}", file=sys.stderr)
        return 3
    except client.SuperDocsError as exc:
        print(f"\nAPI error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
