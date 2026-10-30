#!/usr/bin/env python3
"""The coverage gate: every ledger row has a test, every cited row exists.

`docs/behaviours.md` is only worth writing if it cannot rot. This walks the ledger and the
contract suite and fails on a gap in either direction:

* a behaviour with no test        -- the ledger is claiming something nobody checks
* a test citing a missing row     -- the citation has gone stale

Rows may be excused, but only in writing. An excused row names why it cannot be asserted,
and the excuse is printed on every run so it stays visible instead of quietly becoming
policy.

    python scripts/check_ledger_coverage.py            # summary
    python scripts/check_ledger_coverage.py --verbose  # every row, covered or not
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "behaviours.md"
CONTRACT = ROOT / "contract"

ROW = re.compile(r"^\|\s*(B-\d{3})\s*\|")
CITATION = re.compile(r"\bB-\d{3}\b")

# Rows that cannot be asserted, each with the reason. Kept short on purpose: every entry
# here is a behaviour this suite does not defend, and the list should be uncomfortable
# to add to.
EXCUSED: dict[str, str] = {
    "B-012": "revert is out of scope for this mock's four-call contract",
    "B-013": "same -- revert",
    "B-031": "one-hour job retention cannot be observed inside a test run",
    "B-032": "the one-hour auto-deny, likewise",
    "B-062": "model_fallback fires only when an upstream tier is unhealthy",
    "B-072": "the ~32MB gateway rejection is served by the edge, not the application",
    "B-075": "the 30-minute timeout cannot be provoked responsibly",
    "B-086": "URL lifetimes are wall-clock behaviour, not request/response shape",
    "B-090": "an unbilled error is asserted implicitly by the budget guard",
    "B-101": "archive_document is destructive and outside the four-call contract",
    "B-003": "the mock accepts any bearer by design, so a rejected key cannot be "
             "asserted without shipping a known-bad real key",
    "B-007": "distinguishing an MCP auth 401 from downtime needs a genuinely bad key",
    "B-030": "cancelling a job costs a job to cancel; not worth an operation",
    "B-038": "the continue loop repeating was never observed live -- see the "
             "paused-large-edit synthesis note",
    "B-039": "a continue pause in review mode, likewise unobserved",
    "B-049": "pending_batch_decisions appears only after a reload mid-review, which "
             "the recorded loop never triggered",
    "B-050": "no header/footer/footnote edit was proposed in the recorded turns",
    "B-059": "continue_prompt and documents_changed SSE frames were never observed; "
             "only their polled equivalents were",
    "B-061": "documents_changed needs a multi-document session, outside the "
             "four-call contract this build targets",
    "B-071": "413 document_too_large needs a >100MB export; the capacity refusal "
             "covers the same structured-error shape for a tenth of the load",
    "B-079": "open_mode is multi-document behaviour, outside this build's scope",
}


def ledger_ids() -> list[str]:
    ids: list[str] = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match:
            ids.append(match.group(1))
    return ids


def fixture_ids() -> dict[str, set[str]]:
    """B-IDs a recorded cassette exercises.

    Weaker than a named assertion and tracked separately for that reason: a fixture
    proves the behaviour was observed and that its response validates against the
    published schema, but nobody has written down what about it must stay true.
    """
    import json

    out: dict[str, set[str]] = {}
    for path in sorted((ROOT / "cassettes").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("synthesised"):
            continue  # built from the spec; it cannot be evidence for the spec
        for bid in data.get("covers", []):
            out.setdefault(bid, set()).add(path.stem)
    return out


def cited_ids() -> dict[str, set[str]]:
    """Every B-ID referenced by the suite, mapped to the files citing it."""
    out: dict[str, set[str]] = {}
    for path in sorted(CONTRACT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for bid in CITATION.findall(text):
            out.setdefault(bid, set()).add(path.name)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    defined = ledger_ids()
    cited = cited_ids()
    fixtures = fixture_ids()
    known = set(defined)

    uncovered = [
        b for b in defined
        if b not in cited and b not in fixtures and b not in EXCUSED
    ]
    phantom = sorted(set(cited) - known)
    stale_excuses = sorted(set(EXCUSED) - known)
    excused_but_covered = sorted(b for b in EXCUSED if b in cited)

    asserted = [b for b in defined if b in cited]
    observed = [b for b in defined if b not in cited and b in fixtures]
    print(f"ledger rows             : {len(defined)}")
    print(f"  asserted by a test    : {len(asserted)}")
    print(f"  exercised by a fixture: {len(observed)}   "
          f"(recorded and schema-checked, but not pinned by an assertion)")
    print(f"  excused in writing    : {len(EXCUSED)}")
    print(f"  uncovered             : {len(uncovered)}")

    if args.verbose:
        print()
        for bid in defined:
            if bid in cited:
                mark, note = "test", ", ".join(sorted(cited[bid]))
            elif bid in fixtures:
                mark, note = "fixt", ", ".join(sorted(fixtures[bid]))
            elif bid in EXCUSED:
                mark, note = "excd", EXCUSED[bid]
            else:
                mark, note = "GAP ", ""
            print(f"  {mark} {bid}  {note}")

    problems = False
    if uncovered:
        problems = True
        print("\nBehaviours with no test and no written excuse:", file=sys.stderr)
        for bid in uncovered:
            print(f"  {bid}", file=sys.stderr)
        print("\nEither assert it, or add it to EXCUSED with a reason.", file=sys.stderr)
    if phantom:
        problems = True
        print(f"\nTests cite rows that do not exist: {phantom}", file=sys.stderr)
    if stale_excuses:
        problems = True
        print(f"\nEXCUSED names rows that no longer exist: {stale_excuses}",
              file=sys.stderr)
    if excused_but_covered:
        print(f"\nNote: these are excused but now covered -- drop the excuse: "
              f"{excused_but_covered}", file=sys.stderr)
        problems = True

    if not problems:
        print("\nledger and suite agree")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
