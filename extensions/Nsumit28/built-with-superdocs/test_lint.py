#!/usr/bin/env python3
"""
Negative tests for lint_manifest.py — the mechanical half of the curation rule.

Each case is a way someone could merge an entry without having actually reviewed
it: no evidence link, a one-word reason, a decline citing a reason code the
submitter was never shown. If the lint lets any of those through, the rule in
CURATION.md is a document rather than a gate.

Run:  python3 test_lint.py
"""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from lint_manifest import lint

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "gallery" / "manifest.json"


def drop_evidence(m):
    m["entries"][0]["evidence"] = {"what": "trust me"}
    return m


def thin_note(m):
    m["entries"][0]["reviewer_note"] = "Looks good"
    return m


def invented_code(m):
    m["not_listed"][0]["reason_code"] = "R9"
    return m


def silent_decline(m):
    m["not_listed"][0]["why"] = ""
    return m


def duplicate_slug(m):
    m["entries"].append(copy.deepcopy(m["entries"][0]))
    return m


def insecure_link(m):
    m["entries"][0]["link"] = "http://example.com/thing"
    return m


def no_surface_named(m):
    m["entries"][0]["superdocs_surfaces"] = []
    return m


def missing_review_date(m):
    m["entries"][0]["reviewed_on"] = ""
    return m


CASES = [
    ("entry with no evidence link", drop_evidence, True),
    ("reviewer note too thin to argue with", thin_note, True),
    ("decline citing an unpublished reason code", invented_code, True),
    ("decline with no reason given", silent_decline, True),
    ("two entries sharing a slug", duplicate_slug, True),
    ("link that isn't https", insecure_link, True),
    ("no SuperDocs surface named", no_surface_named, True),
    ("no review date", missing_review_date, True),
    ("the shipped manifest, unmodified", lambda m: m, False),
]


def main() -> int:
    base = json.loads(MANIFEST.read_text(encoding="utf-8"))
    passed = 0

    for name, mutate, expect_failure in CASES:
        m = mutate(copy.deepcopy(base))
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as fh:
            json.dump(m, fh)
            tmp = Path(fh.name)
        try:
            with redirect_stdout(io.StringIO()):
                code = lint(tmp)
        finally:
            tmp.unlink(missing_ok=True)

        caught = code != 0
        ok = caught == expect_failure
        print(f"  {'PASS' if ok else 'FAIL'}  {name} — "
              f"{'caught' if caught else 'allowed'}")
        passed += ok

    print(f"\n{passed}/{len(CASES)} tests passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
