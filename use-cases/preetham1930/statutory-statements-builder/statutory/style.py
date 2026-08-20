"""Table styling, as inline CSS, because that is what measurably survives.

The signed prior-year set uses the legacy `border="1" cellpadding="4"`
attributes. Measured on the first live upload: the product drops them and the
table comes back unstyled. Inline `style` attributes are the ones that survive -
on the styled template fixture all 21 borders, both zebra rows, the header
shading and all 15 right-alignments came back identical, through an upload, a
targeted replace and a DOCX export.

So the roll-forward re-styles the tables on the way through. That is a change to
the signed set's markup and it is deliberate: the deliverable is a typeset
document, and this is the styling the export preserves.
"""

from __future__ import annotations

RULE = "1px solid #1f3864"

TABLE = f"border-collapse:collapse;width:100%;border:{RULE}"
HEAD_ROW = "background-color:#1f3864;color:#ffffff"
TH_TEXT = f"border:{RULE};padding:6px;text-align:left"
TH_NUM = f"border:{RULE};padding:6px;text-align:right"
TD_TEXT = f"border:{RULE};padding:6px"
TD_NUM = f"border:{RULE};padding:6px;text-align:right"
SECTION_ROW = "background-color:#eaeef7"


def table_open() -> str:
    return f'<table style="{TABLE}">'


def head_cell(text: str, numeric: bool = False) -> str:
    return f'<th style="{TH_NUM if numeric else TH_TEXT}">{text}</th>'
