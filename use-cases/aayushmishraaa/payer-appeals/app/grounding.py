"""Does the supplied clinical fact actually address the denial reason?

This module exists because of the specific way an appeal-drafting tool can be dangerous.

The reviewer supplies one denial reason and one clinical fact. Sometimes the fact rebuts the
denial. Sometimes it plainly does not — a note about a patient's blood pressure does not answer
a denial for missing prior authorisation. A model asked to "write an appeal" from those two
inputs will write a fluent, confident, professional letter either way, and the way it bridges
the gap is by inventing clinical detail that nobody documented.

A fabricated clinical assertion in a payer appeal is not a bad user experience. It is a false
statement submitted to an insurer over a clinician's name.

So relevance is checked BEFORE drafting, and the result is shown to the reviewer either way.
The tool still drafts when the fact does not fit — refusing would just push the user to write it
by hand with no warning at all — but it drafts a letter that says what it actually has, and it
tells the reviewer plainly that the fact does not address the stated ground.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Relevance(StrEnum):
    ADDRESSES = "addresses"
    """The fact bears directly on the stated ground for denial."""

    PARTIAL = "partial"
    """Related, but does not by itself answer the ground given."""

    DOES_NOT_ADDRESS = "does_not_address"
    """No discernible connection. Drafting will not invent one."""


@dataclass(frozen=True, slots=True)
class RelevanceCheck:
    verdict: Relevance
    reason: str
    matched_theme: str = ""

    @property
    def should_warn(self) -> bool:
        return self.verdict is not Relevance.ADDRESSES


# Denial grounds and the clinical evidence that actually answers them. Data, not code: a new
# denial category is an entry here.
#
# These are deliberately coarse. The check is a guard against the obviously-wrong pairing, not
# a clinical judgement — it exists to make the reviewer look, not to decide for them.
THEMES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "prior authorisation",
        ("prior auth", "precert", "pre-cert", "preauth", "authorization", "authorisation",
         "carc 197", "no auth", "notification absent"),
        ("authorization", "authorisation", "auth number", "approved", "reference",
         "pa-", "certification", "obtained", "granted", "on file"),
    ),
    (
        "medical necessity",
        ("medical necessity", "not medically necessary", "carc 50", "not deemed",
         "experimental", "investigational"),
        ("conservative", "failed", "physical therapy", "nsaid", "injection", "imaging",
         "mri", "radiograph", "x-ray", "grade", "stenosis", "refractory", "symptoms",
         "diagnosis", "documented", "weeks", "months", "trial of"),
    ),
    (
        "timely filing",
        ("timely filing", "filed late", "untimely", "carc 29", "past the deadline"),
        ("submitted", "date of submission", "postmark", "acknowledg", "received on",
         "claim date", "resubmit"),
    ),
    (
        "coding",
        ("coding", "invalid code", "cpt", "modifier", "unbundl", "carc 16", "ma130",
         "incomplete", "invalid information", "missing information"),
        ("cpt", "code", "modifier", "icd", "npi", "corrected claim", "operative report",
         "procedure performed"),
    ),
    (
        "eligibility",
        ("eligibility", "not covered", "coverage terminated", "not eligible",
         "member not found", "carc 27"),
        ("active coverage", "eligibility", "effective date", "enrolled", "plan end",
         "verification", "270", "271"),
    ),
    (
        "duplicate",
        ("duplicate", "already adjudicated", "carc 18"),
        ("distinct", "separate", "different date", "bilateral", "modifier 59", "unrelated"),
    ),
)


def _hits(text: str, needles: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [n for n in needles if n in lowered]


def check(denial_reason: str, clinical_fact: str) -> RelevanceCheck:
    """Decide whether `clinical_fact` bears on `denial_reason`."""
    if not denial_reason.strip():
        return RelevanceCheck(
            Relevance.DOES_NOT_ADDRESS, "No denial reason was supplied, so nothing to answer."
        )
    if not clinical_fact.strip():
        return RelevanceCheck(
            Relevance.DOES_NOT_ADDRESS,
            "No clinical fact was supplied. An appeal with no supporting fact is a letter of "
            "opinion, and this tool will not dress one up as evidence.",
        )

    for theme, denial_markers, evidence_markers in THEMES:
        if not _hits(denial_reason, denial_markers):
            continue

        evidence = _hits(clinical_fact, evidence_markers)
        if evidence:
            return RelevanceCheck(
                Relevance.ADDRESSES,
                f"The denial is on {theme} grounds and the clinical fact speaks to it "
                f"(matched: {', '.join(evidence[:3])}).",
                matched_theme=theme,
            )

        return RelevanceCheck(
            Relevance.DOES_NOT_ADDRESS,
            f"The denial is on {theme} grounds, but the clinical fact supplied does not "
            f"appear to speak to {theme}. The letter will state the fact accurately and will "
            f"NOT claim it rebuts this ground — check whether you meant to supply different "
            f"documentation.",
            matched_theme=theme,
        )

    # The denial did not match a known theme. Say so rather than guessing, and let the letter
    # be drafted conservatively.
    return RelevanceCheck(
        Relevance.PARTIAL,
        "The denial reason does not match a recognised category, so relevance could not be "
        "assessed. The letter will pair them as given; read it before sending.",
    )


# --------------------------------------------------------------------------------------
# Post-draft check: did the letter invent anything?
# --------------------------------------------------------------------------------------

# Clinical specifics that would be alarming in a letter if they never appeared in the input:
# a fabricated measurement, date or dosage reads as documented fact to a payer.
_SPECIFIC = re.compile(
    r"\b\d+\s?(?:mg|mcg|ml|mm|cm|weeks?|months?|years?|days?|sessions?|degrees?)\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\bgrade\s+[1-4iv]+\b"
    r"|\b\d+\s?(?:percent|%)\b",
    re.IGNORECASE,
)


def unsupported_specifics(draft: str, *sources: str) -> list[str]:
    """Clinical specifics in the draft that appear in none of the source inputs.

    Not a hallucination detector — it cannot judge meaning. It catches the concrete,
    checkable case: a number, date or dosage the letter asserts that nobody supplied. Those
    are exactly the details a payer will verify and a clinician will be asked to stand behind.
    """
    haystack = " ".join(sources).lower()
    found: list[str] = []
    for match in _SPECIFIC.finditer(draft):
        token = match.group(0)
        if token.lower() not in haystack and token not in found:
            found.append(token)
    return found
