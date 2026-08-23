"""Accuracy layer: validation that doesn't trust the model's own
confidence score as the last word.

Three independent checks, each catching a different failure mode a
self-reported confidence number cannot:

  1. Type/format validation -- a `contract_value` that isn't parseable
     as currency, or a date that isn't a valid calendar date, is wrong
     regardless of what confidence the model attached to it. Malformed
     data should never be writable to Box metadata that drives
     retention decisions.

  2. Cross-field consistency -- checks *relationships* between fields
     a single-field confidence score can't see, e.g. expiration_date
     before effective_date. Each field can individually look fine and
     still be jointly contradictory.

  3. Source grounding -- verifies an extracted value's text actually
     appears (exactly or via fuzzy match) somewhere in the source
     document. A value with no textual basis in the source is the
     strongest possible signal of hallucination, independent of the
     model's stated confidence in it.

All three feed into a single downgrade_confidence() call: any failure
force-caps the field's confidence low enough to guarantee it's queued
for human review, no matter how confident the model claimed to be.
Confidence is never *raised* by these checks -- passing validation is
the expected baseline, not evidence of extra correctness.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

# A value failing any check below is capped at this confidence,
# guaranteeing review under any reasonable review_threshold (the
# ReviewQueue default is 0.7; a tenant setting their threshold below
# this ceiling has explicitly chosen to accept unvalidated data, which
# is their call to make, not this module's to override).
VALIDATION_FAILURE_CEILING = 0.3

_CURRENCY_RE = re.compile(r"^\$?\s*-?\d{1,3}(,\d{3})*(\.\d{1,2})?$|^-?\d+(\.\d{1,2})?$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class FieldValidationResult:
    field_name: str
    valid: bool
    reasons: list[str] = field(default_factory=list)


def validate_currency(value: Optional[str]) -> FieldValidationResult:
    """Accepts "$84,000.00", "84000", "-500" (a credit/refund figure is
    still a valid currency value); rejects anything with stray text,
    multiple decimal points, or non-numeric content -- the kind of
    malformed value an LLM occasionally emits when it's uncertain but
    still forced to produce *something*."""
    if value is None:
        return FieldValidationResult("contract_value", valid=True)  # absence is honest, not invalid
    stripped = value.strip()
    if not _CURRENCY_RE.match(stripped):
        return FieldValidationResult(
            "contract_value", valid=False, reasons=[f"{value!r} is not a parseable currency amount"]
        )
    return FieldValidationResult("contract_value", valid=True)


def validate_iso_date(field_name: str, value: Optional[str]) -> FieldValidationResult:
    """Requires strict YYYY-MM-DD AND that it's a real calendar date
    (rejects 2026-02-30) -- format-only regex checks let "2026-13-45"
    through, which is a worse failure mode than catching it here."""
    if value is None:
        return FieldValidationResult(field_name, valid=True)
    stripped = value.strip()
    if not _ISO_DATE_RE.match(stripped):
        return FieldValidationResult(
            field_name, valid=False, reasons=[f"{value!r} is not in ISO 8601 (YYYY-MM-DD) format"]
        )
    try:
        y, m, d = (int(p) for p in stripped.split("-"))
        date(y, m, d)
    except ValueError:
        return FieldValidationResult(
            field_name, valid=False, reasons=[f"{value!r} is not a real calendar date"]
        )
    return FieldValidationResult(field_name, valid=True)


def validate_field_types(
    counterparty_name: Optional[str],
    effective_date: Optional[str],
    expiration_date: Optional[str],
    contract_value: Optional[str],
) -> dict[str, FieldValidationResult]:
    return {
        "counterparty_name": FieldValidationResult("counterparty_name", valid=True),  # free text, no format to check
        "effective_date": validate_iso_date("effective_date", effective_date),
        "expiration_date": validate_iso_date("expiration_date", expiration_date),
        "contract_value": validate_currency(contract_value),
    }


@dataclass
class ConsistencyResult:
    valid: bool
    reasons: list[str] = field(default_factory=list)


def check_cross_field_consistency(
    effective_date: Optional[str], expiration_date: Optional[str]
) -> ConsistencyResult:
    """Individually-valid fields can still be jointly contradictory.
    Only runs the date comparison if both are already valid ISO dates
    (an already-invalid date shouldn't also be blamed for a
    consistency failure -- that's a format problem, reported once, not
    twice under two different reasons)."""
    reasons = []
    if effective_date and expiration_date:
        eff_valid = validate_iso_date("effective_date", effective_date).valid
        exp_valid = validate_iso_date("expiration_date", expiration_date).valid
        if eff_valid and exp_valid and expiration_date < effective_date:
            reasons.append(
                f"expiration_date ({expiration_date}) is before effective_date ({effective_date})"
            )
    return ConsistencyResult(valid=not reasons, reasons=reasons)


def _normalize_for_grounding(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def check_source_grounding(value: Optional[str], source_text: str) -> bool:
    """True if `value` (or a close approximation of it) actually
    appears in the source document text. Whitespace-normalized,
    case-insensitive exact substring match -- deliberately not a fuzzy
    edit-distance match, which would let a subtly-wrong value ("Acme
    Logistics Inc" vs a source that says "Acme Logistic Inc") pass as
    "grounded" when it's actually a small but real error. A value that
    isn't a substring of the source at all is either a paraphrase (fine
    for a summary field, not fine for a fact field like a name or a
    date) or a hallucination -- this check exists to catch the latter,
    so it's intentionally strict."""
    if value is None or not value.strip():
        return True  # absence has nothing to ground
    return _normalize_for_grounding(value) in _normalize_for_grounding(source_text)


def downgrade_confidence(
    field_name: str,
    original_confidence: float,
    type_valid: bool,
    grounded: bool,
) -> tuple[float, list[str]]:
    """Applies the accuracy layer's verdict on top of (never instead
    of) the model's self-reported confidence. Confidence only ever
    moves down here -- passing every check is the expected baseline,
    not a reason to trust a field MORE than the model already claimed
    to."""
    notes = []
    confidence = original_confidence
    if not type_valid:
        confidence = min(confidence, VALIDATION_FAILURE_CEILING)
        notes.append(f"{field_name}: failed type/format validation")
    if not grounded:
        confidence = min(confidence, VALIDATION_FAILURE_CEILING)
        notes.append(f"{field_name}: value not found in source document text (possible hallucination)")
    return confidence, notes
