"""Claim extraction, done the way SuperDocs actually works.

The first attempt asked the chat surface to reply with JSON. It declined --
"I wasn't able to put together a safe reply to share here" -- which is fair:
SuperDocs is a document editor, not a general-purpose structured-output API, and
building on a product means using the shape it actually has.

So the extraction is itself a document. Plumbline asks SuperDocs to write a
claims table, exports it as Markdown, and parses the table. One operation, and
the intermediate artefact is a real document a person can open and read, which
turns out to be a better audit trail than a JSON blob would have been.
"""

from __future__ import annotations

import re

CLAIM_COLUMNS = ["kind", "symbol", "parameter", "value", "quote"]


def build_prompt(doc_text: str, symbols: list[str]) -> str:
    return (
        "Create a document titled 'Extracted claims'. It must contain ONE table "
        "and nothing else -- no introduction, no notes, no closing remarks.\n\n"
        "The table has exactly these columns, in this order:\n"
        "kind | symbol | parameter | value | quote\n\n"
        "One row per checkable claim the documentation makes about the code.\n\n"
        "kind must be exactly one of:\n"
        "  parameter_exists   -- the docs say a function takes a named parameter\n"
        "  parameter_default  -- the docs give a parameter's default value\n"
        "  return_type        -- the docs say what a function returns\n"
        "  raises             -- the docs say a function raises an exception\n"
        "  constant_value     -- the docs give the value of a module constant\n\n"
        "symbol MUST be copied from this list of symbols that exist in the code. "
        "Never write a parameter name in the symbol column; the parameter has its "
        "own column. If a claim cannot be attached to one of these symbols, skip "
        "the claim entirely:\n"
        + "\n".join(f"  {s}" for s in symbols)
        + "\n\nparameter is the parameter name, or empty when the claim is not "
        "about a parameter.\n"
        "value is the value, type or exception name the documentation states.\n"
        "quote is a sentence copied EXACTLY from the documentation, character for "
        "character. It is checked against the source document and a row whose "
        "quote cannot be found is discarded.\n\n"
        "Never invent a symbol, a parameter, or a value. If a sentence makes no "
        "checkable claim of these kinds, it simply has no row.\n\n"
        "DOCUMENTATION:\n" + doc_text
    )


_ESCAPES = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|])")


def _unescape(cell: str) -> str:
    """Markdown export escapes _ and friends; the code does not."""
    return _ESCAPES.sub(r"\1", cell).strip()


def parse_table(markdown: str) -> list[dict]:
    """Pull the claims table out of the generated document.

    Tolerant of the surrounding prose the model sometimes adds anyway, and of
    column order, because relying on the model to obey ordering is a bet that
    does not need taking.
    """
    rows: list[dict] = []
    header: list[str] | None = None

    for line in markdown.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [_unescape(c) for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells if c):
            continue  # the |---|---| separator
        lowered = [c.lower() for c in cells]
        if header is None:
            if "kind" in lowered and "symbol" in lowered:
                header = lowered
            continue
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        row = {header[i]: cells[i] for i in range(len(header))}
        if row.get("kind") and row.get("symbol"):
            rows.append({k: row.get(k, "") for k in CLAIM_COLUMNS})

    return rows
