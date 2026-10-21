"""Load the report design from `templates/report.html` and fill its slots.

The split is deliberate and one-directional: the HTML file owns every style attribute,
this module owns none. Changing how the report looks is an edit to a file a designer can
open in a browser, never a change to Python.

Styling is inline in that file because that is what survives. SuperDocs preserves inline
`style` attributes through the AI edit and through the `.docx` export, where they become
native Word formatting; a `<style>` block in the head is dropped on upload.
"""

from __future__ import annotations

import html
import re
from functools import lru_cache
from pathlib import Path

TEMPLATE = Path(__file__).with_name("templates") / "report.html"

_BLOCK = re.compile(
    r"<!--\s*block:(?P<name>[a-z_]+)\s*-->(?P<body>.*?)<!--\s*/block:(?P=name)\s*-->",
    re.S,
)
_SLOT = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


class TemplateError(RuntimeError):
    """The template file cannot supply what the renderer asked for.

    Raised eagerly rather than emitting half a document: a missing block or an unfilled
    slot would otherwise reach SuperDocs as literal `{{body}}` text and be drafted around
    as though it were content.
    """


@lru_cache(maxsize=1)
def blocks(path: Path | None = None) -> dict[str, str]:
    """Every named block in the template, keyed by name.

    Anything outside a block marker — the doctype, the head, the page chrome that makes
    the file pleasant to open locally — is preview only and is never uploaded.
    """
    source = (path or TEMPLATE).read_text(encoding="utf-8")
    found = {m.group("name"): m.group("body").strip() for m in _BLOCK.finditer(source)}
    if not found:
        raise TemplateError(f"{path or TEMPLATE} defines no blocks")
    return found


def fill(name: str, **values: str) -> str:
    """One block with its slots replaced.

    Values are escaped unless the slot name ends in `_html`, which marks a value that is
    itself rendered markup — a filled block being nested inside its parent.
    """
    try:
        block = blocks()[name]
    except KeyError:
        raise TemplateError(f"template has no block named {name!r}") from None

    def swap(match: re.Match[str]) -> str:
        slot = match.group(1)
        if slot not in values:
            raise TemplateError(f"block {name!r} has slot {{{{{slot}}}}} with no value")
        value = values[slot]
        return value if slot.endswith("_html") else html.escape(value, quote=False)

    out = _SLOT.sub(swap, block)
    unused = set(values) - {m.group(1) for m in _SLOT.finditer(block)}
    if unused:
        raise TemplateError(f"block {name!r} has no slot for {', '.join(sorted(unused))}")
    return out
