#!/usr/bin/env python3
"""Re-apply the current scrubber to every committed cassette.

When the scrubber learns something new, the fixtures already on disk are stale by exactly
that much. Re-recording them would work, and would also spend operations on someone's
quota to fix a bug in this repository -- which is the wrong trade. The scrubber is
deterministic and edits in place, so re-scrubbing a stored cassette produces precisely
what recording it again would have produced.

    python scripts/rescrub_cassettes.py            # clean in place
    python scripts/rescrub_cassettes.py --check    # report, change nothing (CI)

Written after the audit was strengthened to see inside JSON-encoded strings and promptly
found a redemption identifier that the earlier version had passed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sdmock.cassette import dumps  # noqa: E402
from sdmock.scrub import audit, scrub_text, scrub_value  # noqa: E402

CASSETTES = ROOT / "cassettes"


def clean(raw: str) -> str:
    """Key-based redaction on the decoded structure, then textual on the serialised form.

    Both passes are needed and neither subsumes the other: the first sees keys the second
    cannot parse for, and the second sees inside JSON-encoded strings -- MCP tool results
    and the double-encoded proposed_change_batch payload -- that the first walks past.
    """
    structured = scrub_value(json.loads(raw))
    return dumps(json.loads(scrub_text(dumps(structured)))) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report what would change without writing")
    args = ap.parse_args()

    changed: list[str] = []
    still_dirty: list[str] = []

    for path in sorted(CASSETTES.glob("*.json")):
        before = path.read_text(encoding="utf-8")
        after = clean(before)
        problems = audit(after)
        if problems:
            still_dirty.append(f"{path.name}: " + "; ".join(sorted(set(problems))))
        if after != before:
            changed.append(path.name)
            if not args.check:
                path.write_text(after, encoding="utf-8")

    for name in changed:
        print(f"  {'would clean' if args.check else 'cleaned'}  {name}")
    if not changed:
        print("  every cassette is already clean under the current scrubber")

    if still_dirty:
        print("\nSTILL FAILING THE AUDIT after scrubbing:", file=sys.stderr)
        for line in still_dirty:
            print(f"  {line}", file=sys.stderr)
        print("\nThe scrubber cannot reach these. Fix the scrubber, do not "
              "hand-edit a fixture.", file=sys.stderr)
        return 1

    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
