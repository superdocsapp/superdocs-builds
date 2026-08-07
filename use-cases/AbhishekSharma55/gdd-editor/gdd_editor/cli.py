"""`gdd` - the command surface for build #2.

    gdd seed                       # upload the GDD + 3 sub-documents (free)
    gdd scenario --live            # THE GRADED SCENARIO, end to end, asserted
    gdd scenario --live --quick    # same, without the image act (5 ops not 7)
    gdd ask <doc> "instruction"    # one chat-driven edit against one document
    gdd sections [<doc>]           # what the workspace currently holds
    gdd review <doc> "instruction" # HITL: propose, show the diff, approve/deny
    gdd export --format docx       # export every document (free)
    gdd verify                     # re-check the last scenario offline, no key

`scenario` and `ask` spend operations. Everything else is free or offline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from superdocs_kit import OpsBudget, SuperDocs

HERE = Path(__file__).resolve().parent.parent      # gdd-editor/
OUT = HERE / "out"
FIXTURES = HERE.parent / "fixtures" / "gdd-editor"


def _workspace(max_ops: int, live):
    from .workspace import Workspace

    # bool(live), not live: absence of --live must mean REPLAY, never
    # "auto-detect a key and spend money". See the note in the digest CLI.
    budget = OpsBudget(OUT / "ledger.jsonl", max_ops=max_ops)
    client = SuperDocs(budget=budget, cassette_dir=FIXTURES, live=bool(live),
                       log=lambda m: print(f"    {m}"))
    return Workspace(out_dir=OUT, budget=budget, client=client), budget


def cmd_seed(args) -> int:
    ws, budget = _workspace(args.max_ops, args.live)
    print("seeding the Nebula Drift workspace (verbatim uploads, no model)")
    ws.seed()
    for key in ws.docs:
        print(f"  {key:16} {len(ws.docs[key].html):>7}B  "
              f"{len(ws.section_names(key)):>2} sections")
    print(f"\nledger: {json.dumps(budget.summary())}")
    return 0


def cmd_scenario(args) -> int:
    from . import scenario

    ws, budget = _workspace(args.max_ops, args.live)
    print("=" * 78)
    print("THE GRADED SCENARIO")
    print("  'a reviewer asks for a new GDD section plus one linked sub-document,")
    print("   then requests a revision to one mechanic - and only the correct")
    print("   section changes across both documents.'")
    print("=" * 78)
    rep = scenario.run(ws, with_images=not args.quick)
    print(rep.render())
    (OUT / "scenario-report.json").write_text(
        json.dumps({"checks": [c.__dict__ for c in rep.checks], "ops": rep.ops,
                    "seconds": round(rep.seconds, 1), "untouched": rep.untouched},
                   indent=2),
        encoding="utf-8")
    _write_markdown_report(rep)
    print(f"ledger: {json.dumps(budget.summary())}")
    print(f"artefacts: {OUT}")
    return 0 if rep.ok else 1


def _write_markdown_report(rep) -> None:
    lines = ["# Graded scenario - result", "",
             "> *a reviewer asks for a new GDD section plus one linked sub-document,",
             "> then requests a revision to one mechanic - and only the correct",
             "> section changes across both documents.*", "",
             "Regenerate with `gdd scenario --live`. Every row is re-derived from the",
             "document bytes; none of it is taken from the API's own change summary.",
             "", "| # | Check | Result |", "|---|---|---|"]
    for i, c in enumerate(rep.checks, 1):
        lines.append(f"| {i} | {c.name} | {'PASS' if c.ok else '**FAIL**'} |")
    passed = sum(1 for c in rep.checks if c.ok)
    lines += ["", f"**{passed}/{len(rep.checks)} passed** in {rep.ops} billable "
                  f"operations and {rep.seconds:.0f}s.", "",
              "## Per-document surgical check", "",
              "For each act: which sections were allowed to change, which actually",
              "changed, and how many sections came back byte-identical.", "",
              "```json", json.dumps(rep.untouched, indent=2)[:6000], "```"]
    (HERE / "SCENARIO-RESULT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_ask(args) -> int:
    ws, budget = _workspace(args.max_ops, args.live)
    if args.doc not in ws.docs:
        print(f"no document {args.doc!r}. have: {sorted(ws.docs)}\n"
              f"  fix: run `gdd seed` first")
        return 1
    res = ws.edit(args.doc, args.instruction, label=f"ask:{args.doc}",
                  expect_sections=args.only)
    print(f"\n{res.response_text}\n")
    print(f"sections changed: {len(res.changed_sections)}  "
          f"byte-identical: {res.unchanged_sections}")
    if res.verdict:
        print(res.verdict.render())
    return 0


def cmd_review(args) -> int:
    """The human gate, driven from a terminal. Proposes changes, prints the
    diff, takes a decision per change, and proves that denying one does not
    discard the others."""
    from . import review

    ws, budget = _workspace(args.max_ops, args.live)
    if args.doc not in ws.docs:
        print(f"no document {args.doc!r}. have: {sorted(ws.docs)}")
        return 1
    state = ws.docs[args.doc]
    spent_before = budget.spent
    job_id, changes = review.propose(
        ws.client, session_id=state.session_id, document_html=state.html,
        instruction=args.instruction, label=f"review:{args.doc}",
        log=lambda m: print(f"  {m}"),
    )
    if not changes:
        return 0
    print("\nProposed changes:\n" + review.render_diff(changes))

    if args.accept is None:
        raw = input("\nApprove which? (numbers, 'all', 'none'): ").strip().lower()
    else:
        raw = args.accept
    if raw in ("all", "*"):
        keep = set(range(1, len(changes) + 1))
    elif raw in ("none", ""):
        keep = set()
    else:
        keep = {int(x) for x in raw.replace(",", " ").split() if x.isdigit()}
    index = {c.change_id: i for i, c in enumerate(changes, 1)}

    outcome = review.decide(
        ws.client, session_id=state.session_id, job_id=job_id, changes=changes,
        accept=lambda c: index[c.change_id] in keep,
        feedback=args.feedback or "", ops=budget.spent - spent_before,
        log=lambda m: print(f"  {m}"),
    )
    if outcome.final_html:
        state.html = outcome.final_html
        ws._write(args.doc, outcome.final_html)
        ws.save()
    print(f"\n{outcome.summary}")
    print(f"ledger: {json.dumps(budget.summary())}")
    return 0


def cmd_sections(args) -> int:
    ws, _ = _workspace(0, False)
    keys = [args.doc] if args.doc else sorted(ws.docs)
    for key in keys:
        print(f"\n{key}  ({len(ws.docs[key].html)}B)")
        for name in ws.section_names(key):
            print(f"   - {name}")
    return 0


def cmd_export(args) -> int:
    ws, _ = _workspace(0, args.live)
    for p in ws.export_all(args.format):
        print(f"  wrote {p}  ({p.stat().st_size}B)")
    return 0


def cmd_verify(args) -> int:
    """Offline: re-read the committed report and the snapshots, no key needed."""
    path = OUT / "scenario-report.json"
    if not path.exists():
        print(f"no scenario report at {path} - run `gdd scenario --live` first")
        return 1
    data = json.loads(path.read_text())
    bad = [c for c in data["checks"] if not c["ok"]]
    for c in data["checks"]:
        print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['name']}")
    print(f"\n{len(data['checks']) - len(bad)}/{len(data['checks'])} passed, "
          f"{data['ops']} operations")
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gdd", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="upload the GDD and its sub-documents (free)")
    s.add_argument("--live", action="store_true", default=None)
    s.add_argument("--max-ops", type=int, default=0)
    s.set_defaults(func=cmd_seed)

    s = sub.add_parser("scenario", help="run the graded scenario end to end")
    s.add_argument("--live", action="store_true", default=None)
    s.add_argument("--quick", action="store_true", help="skip the image act")
    s.add_argument("--max-ops", type=int, default=12)
    s.set_defaults(func=cmd_scenario)

    s = sub.add_parser("ask", help="one chat-driven edit against one document")
    s.add_argument("doc")
    s.add_argument("instruction")
    s.add_argument("--only", nargs="*", default=None,
                   help="section names this edit is allowed to change")
    s.add_argument("--live", action="store_true", default=None)
    s.add_argument("--max-ops", type=int, default=2)
    s.set_defaults(func=cmd_ask)

    s = sub.add_parser("review", help="propose changes, review the diff, approve or deny")
    s.add_argument("doc")
    s.add_argument("instruction")
    s.add_argument("--accept", default=None,
                   help="non-interactive: 'all', 'none', or change numbers e.g. '1 3'")
    s.add_argument("--feedback", default=None, help="why a change was denied")
    s.add_argument("--live", action="store_true", default=None)
    s.add_argument("--max-ops", type=int, default=12,
                   help="CUMULATIVE cap across this project's whole ledger, not "
                        "per invocation - the ledger persists between runs")
    s.set_defaults(func=cmd_review)

    s = sub.add_parser("sections", help="what the workspace holds (offline)")
    s.add_argument("doc", nargs="?")
    s.set_defaults(func=cmd_sections)

    s = sub.add_parser("export", help="export every document (free)")
    s.add_argument("--format", default="docx",
                   choices=["docx", "pdf", "markdown", "html", "txt"])
    s.add_argument("--live", action="store_true", default=None)
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("verify", help="re-check the last scenario offline")
    s.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
