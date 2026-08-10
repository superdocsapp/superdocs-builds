#!/usr/bin/env python3
"""Recompute the ledger's own summary line from the ledger itself.

The counts printed at the bottom of docs/behaviours.md are generated, not typed, for the
same reason every other number in this project is: a hand-counted total is a claim, and
claims rot. Run this after editing the ledger and paste the output back.

Phase 3 extends this into the CI coverage gate that cross-checks the B-IDs cited by the
contract suite against the B-IDs defined here, failing on a gap in either direction.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

LEDGER = Path(__file__).resolve().parent.parent / "docs" / "behaviours.md"

# | B-001 | B | behaviour text | source | status |
ROW = re.compile(r"^\|\s*(B-\d{3})\s*\|\s*([RMB])\s*\|.*\|\s*([^|]+?)\s*\|\s*$")


def main() -> int:
    if not LEDGER.exists():
        print(f"missing ledger: {LEDGER}", file=sys.stderr)
        return 1

    ids: list[str] = []
    transports: Counter[str] = Counter()
    statuses: Counter[str] = Counter()

    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if not m:
            continue
        bid, transport, status = m.group(1), m.group(2), m.group(3)
        ids.append(bid)
        transports[transport] += 1
        statuses[re.sub(r"[*`]", "", status).split(" ")[0].strip()] += 1

    dupes = [b for b, n in Counter(ids).items() if n > 1]
    numbers = sorted(int(b.split("-")[1]) for b in ids)
    gaps = [n for n in range(1, (numbers[-1] if numbers else 0) + 1) if n not in numbers]

    print(f"behaviours     : {len(ids)}")
    print(f"  REST only    : {transports['R']}")
    print(f"  MCP only     : {transports['M']}")
    print(f"  both         : {transports['B']}")
    print("statuses       : " + ", ".join(f"{k}={v}" for k, v in sorted(statuses.items())))
    print(f"duplicate ids  : {dupes or 'none'}")
    print(f"numbering gaps : {gaps or 'none'}")

    if dupes or gaps:
        print("\nledger is inconsistent", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
