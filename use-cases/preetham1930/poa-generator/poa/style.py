"""Inline CSS, because that is what measurably survives.

Measured on 2026-08-09 and again over Phase 4's live runs: legacy presentational
attributes (`border="1"`) are dropped by the product, while inline `style`
attributes survive an upload, a targeted replace and a DOCX export with every
value intact. So everything this build renders is styled inline.

This module holds **presentation only**. No clause text, no power label, no
notice wording and no jurisdiction name appears here - those are data
(`config/*.csv`), and `test_library.py` fails the build if any of them turns up
as a literal in a `.py` file in this package.
"""

from __future__ import annotations

RULE = "1px solid #1f3864"

TITLE = "font-size:20px;letter-spacing:1px;text-align:center;margin:0 0 12px 0"
BODY = "margin:0 0 10px 0;line-height:1.45"
HEADING = "font-size:14px;margin:16px 0 6px 0"
LIST = "margin:0 0 10px 0;padding-left:22px;line-height:1.45"
ITEM = "margin:0 0 6px 0"
# The notices are the safety-critical content, so they are also the content a
# reader cannot skim past: boxed, ruled, and not the same colour as the clauses.
NOTICE = (
    f"border:{RULE};background-color:#eaeef7;padding:10px;margin:0 0 12px 0;"
    "font-style:italic;line-height:1.4"
)
TABLE = f"border-collapse:collapse;width:100%;border:{RULE}"
HEAD_ROW = "background-color:#1f3864;color:#ffffff"
TH = f"border:{RULE};padding:6px;text-align:left"
TD = f"border:{RULE};padding:6px"
# Signature and date cells are empty and stay empty (INVARIANTS.md A3). The
# height is what makes them look like something to write on, on paper, later.
TD_BLANK = f"border:{RULE};padding:6px;height:34px"

BY_ROLE = {
    "title": TITLE,
    "body": BODY,
    "heading": HEADING,
    "list": LIST,
    "notice": NOTICE,
    "signature": TABLE,
}


def wrap(tag: str, style_role: str, inner: str) -> str:
    return f'<{tag} style="{BY_ROLE[style_role]}">{inner}</{tag}>'
