"""Clause-area patterns, as data.

"Configuration over code" is one of the five behaviours the brief says it reads for: *"A new rule,
court, client, or format should be a data change, not a rewrite."* So the knowledge of what makes a
clause a liability clause lives here, as a table, and the matcher below it is generic.

Adding a clause area, or teaching an existing one a new way of phrasing itself, means editing this
dict. No function changes.

The vocabulary is deliberately about *substance*: `liability` matches "maximum recoverable amount"
and "aggregate liability" and "our total exposure", none of which contain a heading called
LIABILITY. That is what the assigned build means by matching by substance rather than by heading.
"""

from __future__ import annotations

from app.domain.clause import ClauseArea

# Phrases that indicate a clause belongs to an area, lowercased. Matching is substring-based on a
# normalised copy of the text, so ordering and punctuation in the source do not matter.
#
# These are signals, not proof. A span matching a phrase here is a *candidate* — a model-backed
# extractor refines it. The point of the table is that the candidate set is inspectable and
# editable by someone who knows procurement but not Python.
CLAUSE_PHRASES: dict[ClauseArea, tuple[str, ...]] = {
    ClauseArea.LIABILITY: (
        "liability",
        "liable",
        "maximum recoverable amount",
        "aggregate exposure",
        "total exposure",
        "consequential loss",
        "indirect loss",
        "cap on damages",
        "limitation of remedy",
    ),
    ClauseArea.WARRANTY: (
        "warrant",
        "warranty",
        "fitness for purpose",
        "merchantab",
        "free from defects",
        "conforms to specification",
        "defect liability period",
    ),
    ClauseArea.DELIVERY: (
        "delivery",
        "deliver",
        "shipment",
        "ship",
        "lead time",
        "incoterm",
        "ddp",
        "exw",
        "fca",
        "cif",
        "time of the essence",
    ),
    ClauseArea.TITLE_AND_RISK: (
        "title",
        "risk of loss",
        "passes to",
        "retention of title",
        "romalpa",
        "ownership transfers",
    ),
    ClauseArea.PAYMENT: (
        "payment",
        "net 30",
        "net 60",
        "net 45",
        "invoice",
        "payable within",
        "late payment",
        "interest on overdue",
        "set-off",
    ),
    ClauseArea.IP: (
        "intellectual property",
        "background ip",
        "foreground ip",
        "licence",
        "license",
        "patent",
        "copyright",
        "work product",
    ),
    ClauseArea.GOVERNING_LAW: (
        "governing law",
        "governed by the laws",
        "jurisdiction",
        "venue",
        "courts of",
        "arbitration",
        "dispute resolution",
    ),
}


# Phrases that indicate a document is trying to instruct the reader rather than state a term.
# A span matching one of these is reported as a finding, never acted on (INVARIANTS.md I4).
INSTRUCTION_PHRASES: tuple[str, ...] = (
    "ignore your previous instructions",
    "ignore all previous instructions",
    "disregard your instructions",
    "you are an ai",
    "as an ai language model",
    "system prompt",
    "report no conflicts",
    "do not report",
    "approve all",
    "mark this as approved",
    "override the playbook",
)


def areas_for(text: str) -> set[ClauseArea]:
    """Which clause areas a piece of text plausibly belongs to."""
    lowered = text.lower()
    return {area for area, phrases in CLAUSE_PHRASES.items() if any(p in lowered for p in phrases)}


def instruction_phrases_in(text: str) -> tuple[str, ...]:
    """Any attempt by the document to give the system orders. Data to report, never to obey."""
    lowered = text.lower()
    return tuple(phrase for phrase in INSTRUCTION_PHRASES if phrase in lowered)
