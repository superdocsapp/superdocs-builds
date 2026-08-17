#!/usr/bin/env python3
"""
Negative tests for verify_badge.py.

A checker that has only ever returned PASS has not been tested — it has been
admired. Each case below breaks the badge in one specific way that camo's CSP
would punish, and asserts the verifier catches it. The last case asserts the
real badge still passes, so the suite fails if the rules are loosened to fit.

Run:  python3 test_verify.py
"""

from __future__ import annotations

import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from verify_badge import verify

HERE = Path(__file__).resolve().parent
GOOD = HERE / "badge.svg"

# (name, mutation applied to the good SVG source, expect_failure)
CASES = [
    ("script element smuggled in",
     lambda s: s.replace("<title>", "<script>alert(1)</script><title>"), True),

    ("external image reference",
     lambda s: s.replace("<title>",
                         '<image href="https://example.com/logo.png"/><title>'), True),

    ("@font-face pointing at a web font",
     lambda s: s.replace("<title>",
                         '<style>@font-face{font-family:X;src:url(https://a/b.woff2)}</style><title>'),
     True),

    ("live text instead of outlines",
     lambda s: s.replace("<title>",
                         '<text x="0" y="0" font-family="Verdana">built with</text><title>'), True),

    ("width and height stripped",
     lambda s: s.replace('width="133" height="20" ', "", 1), True),

    ("aria-label removed",
     lambda s: s.replace(' aria-label="built with SuperDocs"', "", 1), True),

    ("SMIL animation added",
     lambda s: s.replace("<title>", '<animate attributeName="x" to="5"/><title>'), True),

    ("id un-namespaced back to a single letter",
     lambda s: s.replace("bws-clip", "r"), True),

    ("malformed XML",
     lambda s: s.replace("</svg>", ""), True),

    ("the shipped badge, unmodified",
     lambda s: s, False),
]


def main() -> int:
    if not GOOD.exists():
        print(f"missing {GOOD}; run make_badge.py first")
        return 2

    source = GOOD.read_text(encoding="utf-8")
    passed = 0

    for name, mutate, expect_failure in CASES:
        mutated = mutate(source)
        if mutated == source and expect_failure:
            print(f"  ERROR  {name}: mutation was a no-op, the test is vacuous")
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(mutated)
            tmp = Path(fh.name)
        try:
            with redirect_stdout(io.StringIO()):
                code = verify(tmp)
        finally:
            tmp.unlink(missing_ok=True)

        caught = code != 0
        ok = caught == expect_failure
        verb = "caught" if caught else "allowed"
        print(f"  {'PASS' if ok else 'FAIL'}  {name} — {verb}")
        passed += ok

    print(f"\n{passed}/{len(CASES)} tests passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
