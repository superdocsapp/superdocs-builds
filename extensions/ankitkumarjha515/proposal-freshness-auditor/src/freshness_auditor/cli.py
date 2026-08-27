"""Command line interface.

    audit    find stale claims and write findings.json   (free — no API calls)
    review   decide each finding, interactively or in bulk
    apply    send approved corrections to SuperDocs and prove nothing else moved
    export   write the corrected document out
    report   print the current state of a review

`audit` and `review` never touch the network, so the expensive step is
always explicit and always last.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .corpus import Corpus
from .detect import Finding, detect_all
from .ledger import FactLedger
from .review import (
    Decision,
    ReviewError,
    ReviewItem,
    ReviewSession,
    UnknownFindingError,
    build_batches,
    render_finding,
    render_summary,
)
from .superdocs import AuthError, FakeSuperDocsClient, McpSuperDocsClient

DEFAULT_STATE = Path("findings.json")


class AmbiguousIdError(ReviewError):
    """Raised when an id prefix could mean more than one finding."""


# -- naming a finding ------------------------------------------------------


def _resolve_ids(session: ReviewSession, tokens: list[str]) -> list[str]:
    """Turn what a reviewer can see on screen into ids the session holds.

    `audit` prints findings as [1], [2], [3]; the ids underneath are content
    hashes. Accepting only the hash made the printed index a lie, so a token
    is resolved three ways: as an exact id, as the 1-based display index, or
    as an unambiguous id prefix.

    Exact ids are tried first. A hex id can come out all digits, and an id
    must never be stolen by the index lookup. An ambiguous prefix is refused
    rather than guessed — guessing here would approve an edit nobody chose.
    """
    items = session.items()
    ids = [i.finding.id for i in items]
    known = set(ids)
    resolved: list[str] = []

    for raw in tokens:
        token = raw.strip()

        if token in known:
            resolved.append(token)
            continue

        if token.isdigit():
            n = int(token)
            if not 1 <= n <= len(ids):
                raise UnknownFindingError(
                    f"no finding [{token}] — this review holds "
                    f"{len(ids)} finding(s), numbered 1 to {len(ids)}. "
                    f"Run `report` to see them."
                )
            resolved.append(ids[n - 1])
            continue

        hits = [i for i in ids if i.startswith(token.lower())]
        if len(hits) == 1:
            resolved.append(hits[0])
            continue
        if len(hits) > 1:
            raise AmbiguousIdError(
                f"{token!r} matches {len(hits)} findings ({', '.join(hits)}) "
                f"— use more characters, or the number shown in `report`."
            )
        raise UnknownFindingError(
            f"{token!r} is not a finding in this review. Use the number "
            f"shown in `report` (1 to {len(ids)}), or a finding id."
        )

    return resolved


# -- state -----------------------------------------------------------------


def _finding_to_dict(f: Finding) -> dict:
    d = asdict(f)
    d["as_of"] = str(f.as_of)
    d["matched_prior"] = {
        "value": f.matched_prior.value,
        "as_of": str(f.matched_prior.as_of),
        "retired_on": str(f.matched_prior.retired_on),
    }
    return d


def save_state(session: ReviewSession, path: Path) -> None:
    payload = {
        "version": 1,
        "items": [
            {
                "decision": i.decision.value,
                "note": i.note,
                "finding": _finding_to_dict(i.finding),
            }
            for i in session.items()
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_state(path: Path, ledger: FactLedger, corpus: Corpus) -> ReviewSession:
    """Rebuild a session, re-deriving findings so decisions bind to real ones.

    Findings are re-detected rather than trusted from disk, and decisions
    re-attached by deterministic finding id. If a document changed under us,
    a decision whose finding no longer exists is dropped rather than applied
    to something else.
    """
    if not path.exists():
        raise SystemExit(
            f"no review state at {path} — run `audit` first to create it"
        )
    saved = json.loads(path.read_text(encoding="utf-8"))
    decisions = {
        it["finding"]["id"]: (it["decision"], it.get("note"))
        for it in saved.get("items", [])
    }

    findings = _detect(ledger, corpus)
    items = []
    for f in findings:
        dec, note = decisions.get(f.id, ("pending", None))
        items.append(
            ReviewItem(finding=f, decision=Decision(dec), note=note)
        )
    dropped = len(decisions) - sum(1 for f in findings if f.id in decisions)
    if dropped > 0:
        print(
            f"note: {dropped} saved decision(s) no longer match any finding "
            f"(the documents changed) and were dropped.",
            file=sys.stderr,
        )
    return ReviewSession(items)


def _detect(ledger: FactLedger, corpus: Corpus) -> list[Finding]:
    findings: list[Finding] = []
    for doc in corpus.documents():
        findings.extend(detect_all(corpus.read_text(doc.id), doc.id, ledger))
    return findings


def _load(args) -> tuple[FactLedger, Corpus]:
    return FactLedger.load(args.facts), Corpus.load(args.corpus)


# -- commands --------------------------------------------------------------


def cmd_audit(args) -> int:
    ledger, corpus = _load(args)
    findings = _detect(ledger, corpus)
    session = ReviewSession.from_findings(findings)
    save_state(session, Path(args.state))

    if not findings:
        print("No stale claims found. The corpus is clean.")
        print(f"(checked {len(corpus.documents())} document(s) against "
              f"{len(ledger.facts)} fact(s))")
        return 0

    for n, item in enumerate(session.items(), start=1):
        print(render_finding(item, index=n))
        print()
    print(render_summary(session))
    print(f"\nSaved to {args.state}. Next: `review` to decide, then `apply`.")
    return 0


def cmd_review(args) -> int:
    ledger, corpus = _load(args)
    session = load_state(Path(args.state), ledger, corpus)

    if args.approve_all:
        session.approve_all()
    elif args.reject_all:
        session.reject_all(note=args.note)
    elif args.approve:
        # Resolve every token before deciding anything: a typo in the third
        # id must not leave the first two already approved.
        for fid in _resolve_ids(session, args.approve):
            session.approve(fid, args.note)
    elif args.reject:
        for fid in _resolve_ids(session, args.reject):
            session.reject(fid, args.note)
    else:
        return _interactive(session, Path(args.state))

    save_state(session, Path(args.state))
    print(render_summary(session))
    return 0


def _interactive(session: ReviewSession, state_path: Path) -> int:
    items = session.items()
    print(f"{len(items)} finding(s) to review. "
          f"[a]pprove  [r]eject  [s]kip  [q]uit and save\n")
    for n, item in enumerate(items, start=1):
        print(render_finding(item, index=n))
        while True:
            try:
                choice = input("    decision [a/r/s/q]: ").strip().lower()
            except EOFError:
                choice = "q"
            if choice in {"a", "r", "s", "q"}:
                break
            print("    please answer a, r, s or q")
        if choice == "a":
            session.approve(item.finding.id)
        elif choice == "r":
            note = input("    reason (optional): ").strip() or None
            session.reject(item.finding.id, note)
        elif choice == "q":
            break
        print()

    save_state(session, state_path)
    print(render_summary(session))
    return 0


def cmd_apply(args) -> int:
    from .apply import apply_batches  # imported here to keep `audit` import-light

    ledger, corpus = _load(args)
    session = load_state(Path(args.state), ledger, corpus)
    batches = build_batches(session)

    if not batches:
        print("Nothing approved — no operations will be spent.")
        return 0

    print(f"{len(batches)} batch(es) → {len(batches)} operation(s) at most.")
    if args.dry_run:
        from .apply import instruction_for
        for b in batches:
            print(f"\n--- {b.doc_id} (part {b.part}/{b.of_parts}) ---")
            print(instruction_for(b))
        print("\nDry run: nothing sent, nothing spent.")
        return 0

    if args.fake:
        client = FakeSuperDocsClient()
    else:
        try:
            client = McpSuperDocsClient()
        except AuthError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    sources = {b.doc_id: corpus.read_text(b.doc_id) for b in batches}
    run = apply_batches(client, batches, sources=sources,
                        max_operations=args.max_operations)
    print(run.render())
    return 0 if run.ok else 1


def cmd_export(args) -> int:
    if args.fake:
        print("error: export needs a live session; --fake has no stored document",
              file=sys.stderr)
        return 2
    try:
        client = McpSuperDocsClient()
    except AuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = client.export(args.session_id, args.format)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(out)
    return 0


def cmd_report(args) -> int:
    ledger, corpus = _load(args)
    session = load_state(Path(args.state), ledger, corpus)
    for n, item in enumerate(session.items(), start=1):
        print(render_finding(item, index=n))
        print()
    print(render_summary(session))
    return 0


# -- wiring ----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="freshness-auditor",
        description="Find and correct stale boilerplate facts across proposals.",
    )
    p.add_argument("--facts", default="fixtures/facts.yaml",
                   help="path to the fact ledger (default: %(default)s)")
    p.add_argument("--corpus", default="fixtures/corpus.yaml",
                   help="path to the corpus registry (default: %(default)s)")
    p.add_argument("--state", default=str(DEFAULT_STATE),
                   help="review state file (default: %(default)s)")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("audit", help="find stale claims (free, no API calls)")
    a.set_defaults(func=cmd_audit)

    r = sub.add_parser("review", help="decide findings")
    r.add_argument("--approve", nargs="*", metavar="ID")
    r.add_argument("--reject", nargs="*", metavar="ID")
    r.add_argument("--approve-all", action="store_true")
    r.add_argument("--reject-all", action="store_true")
    r.add_argument("--note", default=None, help="note attached to the decision")
    r.set_defaults(func=cmd_review)

    ap = sub.add_parser("apply", help="apply approved corrections via SuperDocs")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the instructions without sending anything")
    ap.add_argument("--fake", action="store_true",
                    help="run against the offline fake client")
    ap.add_argument("--max-operations", type=int, default=8,
                    help="hard stop on operations spent (default: %(default)s)")
    ap.set_defaults(func=cmd_apply)

    e = sub.add_parser("export", help="export a session's document")
    e.add_argument("session_id")
    e.add_argument("--format", default="html",
                   choices=["html", "markdown", "txt", "docx", "pdf"])
    e.add_argument("--out", default=None)
    e.add_argument("--fake", action="store_true")
    e.set_defaults(func=cmd_export)

    rep = sub.add_parser("report", help="show the current review state")
    rep.set_defaults(func=cmd_report)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ReviewError, AuthError) as e:
        # A reviewer who mistypes an id gets the cause and the fix, not a
        # stack trace. Anything unexpected still raises, loudly.
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
