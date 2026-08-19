"""Verifies that a lead's recap document, as actually produced by
SuperDocs, contains exactly what app/recap_content.py decided it should
— not just that we *asked* for the right substitution.

app/recap_content.py already makes the "no invented specifics" guarantee
structural at the Python layer: the values that go into the chat
instruction are fixed strings built from one Lead record, never model
output. But the chat instruction is still, ultimately, a request to an
AI editor — asking it to substitute exact text is not the same as being
mathematically certain it did. This module closes that gap by reading
the SuperDocs-produced document back (a free, non-billable 'txt' export;
see docs.superdocs.app/account/plans-and-usage#what-counts-as-an-operation)
and checking, mechanically, that:

  1. no unresolved {{token}} placeholders remain (the substitution
     actually happened), and
  2. every one of this lead's own section values appears in the output
     (nothing was dropped or paraphrased away).

This does not re-check cross-lead isolation — that guarantee is already
proven at the instruction-construction layer in
tests/test_no_cross_contamination.py, which is the correct place to
prove it exhaustively (checking every other lead's distinctive strings
against every document). This module's job is narrower and
complementary: prove *this* lead's own recap actually landed correctly
in the document SuperDocs produced, not just in the instruction we sent.

`find_unresolved_tokens` and `missing_expected_fields` are exposed
separately (not just folded into `verify_recap_text`'s prose) so
app/batch.py can build a precise, targeted cleanup instruction naming
exactly what's still wrong, rather than re-parsing human-readable
strings — see app/batch.py's "Found running against the live API"
comment for why that targeted cleanup pass exists.
"""

from __future__ import annotations

import re

from app.recap_content import RecapSections

_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_]+)\s*\}\}")


def find_unresolved_tokens(text: str) -> list[str]:
    """Returns the distinct token names (without braces) still present
    as unresolved {{token}} placeholders in `text`, in first-seen order."""
    seen: list[str] = []
    for match in _PLACEHOLDER_PATTERN.finditer(text):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def missing_expected_fields(text: str, sections: RecapSections) -> list[str]:
    """Returns the names of RecapSections fields whose exact value does
    not appear anywhere in `text` — catches the case where a
    placeholder token itself was removed but the correct value wasn't
    actually substituted in (e.g. replaced with something paraphrased)."""
    expected = {
        "lead_name": sections.lead_name,
        "lead_company": sections.lead_company,
        "discussion_section": sections.discussion_section,
        "promised_section": sections.promised_section,
        "next_step_section": sections.next_step_section,
    }
    return [name for name, value in expected.items() if value and value not in text]


def verify_recap_text(text: str, sections: RecapSections) -> list[str]:
    """Returns a list of human-readable problems found in `text`. An
    empty list means the export looks correct."""
    problems: list[str] = []

    unresolved = find_unresolved_tokens(text)
    if unresolved:
        problems.append(
            f"{len(unresolved)} unresolved placeholder token(s) still present: "
            f"{[f'{{{{{token}}}}}' for token in unresolved]}"
        )

    for field_name in missing_expected_fields(text, sections):
        problems.append(f"expected {field_name} text not found in exported document")

    return problems
