"""What replaces the text — and why it is not `[REDACTED]`.

`[REDACTED]` destroys what kind of thing was there; a typed marker keeps a
released copy reviewable and makes over-redaction obvious. `[NAME REDACTED]`
still says who owed what to whom.

Typed from the detector, not a guess: tier 1's `kind` is exact (`ssn`,
`credit_card`); tier 3's is the model's wording, so it is normalised against the
table below and falls back to the category. An unrecognised kind becomes
`[PERSONAL DATA REDACTED]`, never a marker invented from the model's phrasing.

See extensions/redaction-pane/README.md § "What replaces the text".
"""

from __future__ import annotations

import re

from .pii.patterns import ACCOUNT, HEALTH, PERSONAL, PRIVILEGED

BY_CATEGORY = {
    PERSONAL: "PERSONAL DATA",
    HEALTH: "HEALTH DATA",
    ACCOUNT: "ACCOUNT DETAIL",
    PRIVILEGED: "PRIVILEGED CONTENT",
}
"""The floor. Every candidate has a category, so every candidate has a marker."""

BY_KIND: tuple[tuple[tuple[str, ...], str], ...] = (
    # Order matters: the first tuple whose words all appear in the normalised
    # kind wins, so the specific entries come before the general ones.
    (("social", "security"), "SSN"),
    (("ssn",), "SSN"),
    (("credit", "card"), "CREDIT CARD"),
    (("card",), "CREDIT CARD"),
    (("routing",), "ROUTING NUMBER"),
    (("sort", "code"), "SORT CODE"),
    (("iban",), "IBAN"),
    (("account",), "ACCOUNT NUMBER"),
    (("passport",), "PASSPORT NUMBER"),
    (("insurance",), "INSURANCE ID"),
    (("medical", "record"), "MEDICAL RECORD"),
    (("mrn",), "MEDICAL RECORD"),
    (("credential",), "CREDENTIAL"),
    (("birth",), "DATE OF BIRTH"),
    (("dob",), "DATE OF BIRTH"),
    (("email",), "EMAIL"),
    (("phone",), "PHONE NUMBER"),
    (("address",), "ADDRESS"),
    (("name",), "NAME"),
    (("person",), "NAME"),
    (("diagnos",), "HEALTH DATA"),
    (("prescri",), "HEALTH DATA"),
    (("treatment",), "HEALTH DATA"),
    (("condition",), "HEALTH DATA"),
    (("settlement",), "SETTLEMENT POSITION"),
    (("litigation",), "LEGAL STRATEGY"),
    (("advice",), "LEGAL ADVICE"),
)

_WORDS = re.compile(r"[^a-z]+")


def label(category: str, kind: str) -> str:
    """`("account", "credit_card")` → `"CREDIT CARD"`."""
    normalised = _WORDS.sub(" ", (kind or "").lower())
    for words, name in BY_KIND:
        if all(word in normalised for word in words):
            return name
    return BY_CATEGORY.get(category, "SENSITIVE")


def marker(category: str, kind: str) -> str:
    """What is written in place of the span. Brackets and REDACTED, the
    convention a records officer reads, so a removal is obvious on the page."""
    return f"[{label(category, kind)} REDACTED]"
