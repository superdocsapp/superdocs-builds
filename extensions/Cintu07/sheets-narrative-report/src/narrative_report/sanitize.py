"""Treating spreadsheet text as data.

This lives in its own module because sanitisation has to happen at the boundary
where the sheet is read, before facts, prompts or documents are built from it.
An earlier version sanitised only the document skeleton, and hostile row text
still reached the model through the fact table's ``label`` column, the fix for
that class of bug is one chokepoint, not a filter at each consumer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_LABEL_CHARS = 80

# Phrasings whose only purpose in a spreadsheet cell is to address the model.
INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(all\s+)?(previous|prior|above)|disregard\s+(the\s+)?(above|previous)"
    r"|system\s*prompt|you\s+are\s+now|new\s+instructions?|act\s+as"
    r"|</?\s*(script|system|instructions?)\s*>|\{\{\s*fact\s*:)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SanitisedLabel:
    original: str
    safe: str
    flagged: bool


def sanitise_label(label: str) -> SanitisedLabel:
    """Make a spreadsheet label safe to place in a prompt or a document.

    Collapses whitespace, caps length, and neutralises text that is addressing
    the model. The original is preserved so the attempt can be shown to the
    human, a sheet trying to steer the system is something they should see,
    not something we should quietly absorb.
    """
    collapsed = re.sub(r"\s+", " ", str(label)).strip()
    flagged = bool(INJECTION_PATTERNS.search(collapsed))
    safe = INJECTION_PATTERNS.sub("[redacted]", collapsed)[:MAX_LABEL_CHARS].strip()
    return SanitisedLabel(original=collapsed, safe=safe or "unnamed item", flagged=flagged)
