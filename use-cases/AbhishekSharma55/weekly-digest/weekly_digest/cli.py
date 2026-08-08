"""`digest` - the command surface for build #1.

    digest run     --weeks 52 --max-ops 70     # arm A: edit in place
    digest regen   --weeks 12 --max-ops 40     # arm B: regenerate weekly
    digest report                              # cost comparison + drift report
    digest verify                              # re-check every saved week, offline
    digest diff --week 30                      # what changed between week 29 and 30

Every command is safe to re-run. `run` resumes from the ledger; `report`,
`verify` and `diff` touch no network at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from superdocs_kit import OpsBudget, SuperDocs

HERE = Path(__file__).resolve().parent.parent          # weekly-digest/
DATA = HERE / "data" / "weeks.json"
OUT = HERE / "out"
FIXTURES = HERE.parent / "fixtures" / "weekly-digest"
RUN_ID = "nebula-digest-v1"


def load_weeks() -> list[dict]:
    if not DATA.exists():
        raise SystemExit(
            f"{DATA} is missing.\n  fix: python {HERE / 'data' / 'build_corpus.py'}"
        )
    return json.loads(DATA.read_text(encoding="utf-8"))


def _client(budget: OpsBudget, live, cassette: Path) -> SuperDocs:
    """`live` is coerced to a real bool on purpose.

    It used to be passed through as None when --live was absent, which made
    build_transport "auto-detect": it found a key in .env and went live. So a
    command a reader would reasonably believe was a dry run spent five real
    operations. Absence of --live now means REPLAY, unconditionally - the
    expensive path has to be asked for by name.
    """
    return SuperDocs(budget=budget, cassette_dir=cassette, live=bool(live),
                     log=lambda m: print(f"  {m}"))


def cmd_run(args) -> int:
    from .runner import DigestRun

    weeks = load_weeks()
    # --out lets a replay write somewhere else, so re-running from fixtures can
    # never overwrite the committed artefacts of the live run it is replaying.
    out = Path(args.out) if args.out else OUT / "arm-a-edit"
    budget = OpsBudget(out / "ledger.jsonl", max_ops=args.max_ops)
    client = _client(budget, args.live, FIXTURES / "arm-a")
    run = DigestRun(weeks=weeks, out_dir=out, budget=budget, client=client,
                    session_id=f"{RUN_ID}-arm-a")
    print(f"arm A - edit in place · weeks 1..{args.weeks} · cap {args.max_ops} ops "
          f"· already spent {budget.spent}")
    run.run(args.weeks)
    print(f"\nledger: {json.dumps(budget.summary())}")
    print(f"artefacts: {out}")
    return 0


def cmd_regen(args) -> int:
    from .regenerate import RegenerateRun

    weeks = load_weeks()
    out = Path(args.out) if args.out else OUT / "arm-b-regenerate"
    budget = OpsBudget(out / "ledger.jsonl", max_ops=args.max_ops)
    client = _client(budget, args.live, FIXTURES / "arm-b")
    run = RegenerateRun(weeks=weeks, out_dir=out, budget=budget, client=client, run_id=RUN_ID)
    print(f"arm B - regenerate weekly · weeks 1..{args.weeks} · cap {args.max_ops} ops "
          f"· already spent {budget.spent}")
    run.run(args.weeks)
    print(f"\nledger: {json.dumps(budget.summary())}")
    return 0


def cmd_report(args) -> int:
    from .measure import write_report

    path = write_report(OUT, load_weeks())
    print(f"wrote {path}")
    print(path.read_text(encoding="utf-8")[:3000])
    return 0


def cmd_verify(args) -> int:
    """Offline re-verification of every saved week. No key, no network."""
    from .verify import check_week, drift_table

    weeks = load_weeks()
    html_dir = OUT / "arm-a-edit" / "html"
    reports = []
    for path in sorted(html_dir.glob("week-*.html")):
        n = int(path.stem.split("-")[1])
        reports.append(check_week(path.read_text(encoding="utf-8"), weeks[n - 1]))
    if not reports:
        print(f"no saved weeks in {html_dir} - run `digest run` first")
        return 1
    print(drift_table(reports))
    bad = [r for r in reports if not r.ok]
    print(f"\n{len(reports) - len(bad)}/{len(reports)} weeks clean")
    for r in bad:
        for c in r.failures:
            print(f"  week {r.week}: [{c.group}] {c.name} - {c.detail[:160]}")
    return 0


_ATTRIB_STOP = set(
    "the a an and or of to in for with on at from is are was were shipped summary "
    "risks carried remain open completed first pass one this that".split()
)


def _content_words(text: str) -> set[str]:
    import re

    return {
        w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if w not in _ATTRIB_STOP and len(w) > 3
    }


def cmd_archive_check(args) -> int:
    """Is each archive row about the week it is labelled with? Offline, free.

    THE CHECK THAT EXISTS BECAUSE NO INVARIANT COULD DO IT (bugs.md M7).

    Every invariant on the archive is structural - coverage, bounds, labels - and
    none of them reads the sentence the model wrote. That is how, for seven
    weeks, the row labelled "Week 5" came to describe what week 6 shipped: the
    instruction said "summarise the bullets currently under 'What changed'" while
    a later step of the same turn replaced those bullets.

    This cannot be an invariant, because a summary is prose and grading prose
    needs a rubric and a second model call. What it can be is a cheap, offline
    attribution test with a stated method: take the distinctive content words of
    each row and count how many belong to the week it claims to describe, versus
    how many belong ONLY to the week after it. A row about the right week scores
    zero on the second count.

    Its limit, stated: it detects the off-by-one that actually happened. It does
    not check that the summary is *true*, only that it is about the right week.
    """
    import re

    weeks = load_weeks()
    html_dir = OUT / "arm-a-edit" / "html"
    saved = sorted(html_dir.glob("week-*.html"))
    if not saved:
        print(f"no saved weeks in {html_dir} - run `digest run --live` first")
        return 1

    print("Each archive row, at the moment it was filed.")
    print("method: distinctive words of the row, matched against the week it names")
    print("        versus words belonging only to the following week.\n")
    print("| filed at | row | words from its own week | words only from the next week | verdict |")
    print("|---|---|---|---|---|")
    suspect = []
    for path in saved:
        n = int(path.stem.split("-")[1])
        if n < 2 or n > len(weeks):
            continue
        block = re.search(r"<h2[^>]*>\s*Archive.*", path.read_text(encoding="utf-8"), re.S)
        if not block:
            continue
        row_text = None
        for raw in re.findall(r"<tr[^>]*>(.*?)</tr>", block.group(0), re.S):
            cells = [
                re.sub(r"<[^>]+>", "", c).strip()
                for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", raw, re.S)
            ]
            if len(cells) >= 3 and cells[0] == f"Week {n - 1}":
                row_text = cells[2]
        if row_text is None:
            continue
        row_words = _content_words(row_text)
        own = _content_words(" ".join(weeks[n - 2]["shipped"]))
        nxt = _content_words(" ".join(weeks[n - 1]["shipped"]))
        hits, strays = len(row_words & own), len(row_words & (nxt - own))
        ok = hits > 0 and hits >= strays
        if not ok:
            suspect.append(n - 1)
        print(f"| week {n} | Week {n - 1} | {hits} | {strays} | {'ok' if ok else '**SUSPECT**'} |")

    total = len(saved) - 1
    print(f"\n**{len(suspect)} row(s) describing the wrong week**, out of {total} filed.")
    if suspect:
        print(f"suspect rows: {suspect}")
        print("  fix: check archive.plan_rows - the text to summarise must be handed "
              "over literally, never named as a place in the document.")
    return 0 if not suspect else 1


def cmd_diff(args) -> int:
    p = OUT / "arm-a-edit" / "diff" / f"week-{args.week:02d}.diff"
    if not p.exists():
        print(f"no diff at {p}")
        return 1
    print(p.read_text(encoding="utf-8"))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="digest", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="arm A: edit one document, week by week")
    r.add_argument("--weeks", type=int, default=52)
    r.add_argument("--max-ops", type=int, default=70,
                   help="hard cap on billable operations for this arm")
    r.add_argument("--live", action="store_true", default=None)
    r.add_argument("--out", default=None,
                   help="write artefacts here instead of out/arm-a-edit. Use it for "
                        "replays, so re-running from fixtures can never overwrite the "
                        "committed artefacts of the live run it is replaying.")
    r.set_defaults(func=cmd_run)

    g = sub.add_parser("regen", help="arm B: regenerate the digest weekly (the control)")
    g.add_argument("--weeks", type=int, default=12)
    g.add_argument("--max-ops", type=int, default=40)
    g.add_argument("--live", action="store_true", default=None)
    g.add_argument("--out", default=None)
    g.set_defaults(func=cmd_regen)

    for name, fn, helptext in (
        ("report", cmd_report, "write the cost comparison from the two ledgers"),
        ("verify", cmd_verify, "re-check every saved week offline"),
        ("archive-check", cmd_archive_check,
         "is each archive row about the week it names? (offline, bugs.md M7)"),
    ):
        s = sub.add_parser(name, help=helptext)
        s.set_defaults(func=fn)

    d = sub.add_parser("diff", help="show one week-over-week diff")
    d.add_argument("--week", type=int, required=True)
    d.set_defaults(func=cmd_diff)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
