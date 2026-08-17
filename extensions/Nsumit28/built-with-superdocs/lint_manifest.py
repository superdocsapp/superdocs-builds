#!/usr/bin/env python3
"""
Enforce the parts of the curation rule a machine can actually enforce.

Be clear about what this does and does not do. It cannot tell whether SuperDocs
did work that mattered — that is the second test in CURATION.md and it needs a
human who opened both links. What it can do is make it **impossible to merge an
entry that has no recorded decision, no evidence link, and no stated reason.**

That distinction is the whole point. A curation rule that lives only in a
markdown file decays the first time someone is in a hurry. A rule that fails the
build when the reason field is empty does not. So: the judgement stays human, and
the paper trail is mechanical.

Run:  python3 lint_manifest.py [gallery/manifest.json]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HTTPS = re.compile(r"^https://", re.I)

# The decline reasons published in CURATION.md. A code outside this set means
# someone invented a reason that the submitter was never shown.
REASON_CODES = {"R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"}

REQUIRED_LISTED = ("slug", "name", "summary", "link", "superdocs_surfaces",
                   "evidence", "submitted_by", "reviewed_on", "decision",
                   "reviewer_note")
REQUIRED_DECLINED = ("name", "decision", "reason_code", "why", "reviewed_on")


def lint(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    problems: list[str] = []

    def bad(where: str, msg: str) -> None:
        problems.append(f"{where}: {msg}")

    entries = data.get("entries", [])
    declined = data.get("not_listed", [])

    seen_slugs: set[str] = set()
    for i, e in enumerate(entries):
        where = f"entries[{i}] ({e.get('slug') or e.get('name') or '?'})"

        for field in REQUIRED_LISTED:
            if not e.get(field):
                bad(where, f"missing required field '{field}'")

        if e.get("decision") not in {"listed", "declined"}:
            bad(where, f"decision must be listed or declined, got {e.get('decision')!r}")

        slug = e.get("slug")
        if slug:
            if slug in seen_slugs:
                bad(where, f"duplicate slug '{slug}'")
            seen_slugs.add(slug)
            if not re.fullmatch(r"[a-z0-9-]+", slug):
                bad(where, f"slug '{slug}' should be lowercase-hyphenated")

        # Test 1 and test 3 both need something a stranger can open.
        for field, val in (("link", e.get("link")),
                           ("evidence.url", (e.get("evidence") or {}).get("url"))):
            if val and not HTTPS.match(val):
                bad(where, f"{field} must be an https URL a reviewer can open, got {val!r}")
        if not (e.get("evidence") or {}).get("url"):
            bad(where, "no evidence URL — test 3 of the bar cannot be checked")

        if e.get("reviewed_on") and not ISO_DATE.match(e["reviewed_on"]):
            bad(where, f"reviewed_on must be YYYY-MM-DD, got {e['reviewed_on']!r}")

        note = (e.get("reviewer_note") or "").strip()
        if len(note.split()) < 6:
            bad(where, "reviewer_note is too thin to be a reason someone could argue with")

        surfaces = e.get("superdocs_surfaces") or []
        if not surfaces:
            bad(where, "no SuperDocs surface named — test 2 cannot be checked")

    for i, d in enumerate(declined):
        where = f"not_listed[{i}] ({d.get('name', '?')})"
        for field in REQUIRED_DECLINED:
            if not d.get(field):
                bad(where, f"missing required field '{field}'")
        code = d.get("reason_code")
        if code and code not in REASON_CODES:
            bad(where, f"reason_code {code!r} is not one of the published reasons "
                       f"{sorted(REASON_CODES)}")
        if d.get("reviewed_on") and not ISO_DATE.match(d["reviewed_on"]):
            bad(where, f"reviewed_on must be YYYY-MM-DD, got {d['reviewed_on']!r}")
        if len((d.get("why") or "").split()) < 6:
            bad(where, "a decline needs a reason the submitter can read and answer")

    print(f"\n{path}")
    print(f"  {len(entries)} listed, {len(declined)} declined\n")

    if problems:
        for p in problems:
            print(f"  FAIL  {p}")
        print(f"\n{len(problems)} problem(s). No entry merges until every decision "
              "carries evidence and a reason.")
        return 1

    print("  PASS  every entry carries a decision, an evidence link and a stated reason")
    print("\nWhat this cannot check: whether SuperDocs actually did work that "
          "mattered. That is test 2, and it needs a human who opened both links.")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "gallery" / "manifest.json"
    sys.exit(lint(target))
