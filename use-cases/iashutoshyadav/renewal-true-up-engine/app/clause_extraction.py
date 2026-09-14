"""Deterministic, regex-based extraction of the three governing-clause facts (entitlement, monthly fee,
overage rate) from a contract's plain text.

Deliberate scope decision, not an oversight: this is regex over a declared, consistent contract phrasing
style (the synthetic corpus this build ships with), not a general-purpose NLP/LLM extractor. Mirrors the
same trade-off Task 1's fake LLM provider made, for the same reason - deterministic and offline means every
test in this project runs without a live key or network call, which the round's own standard requires.
A real production version of this tool would likely swap this module for an LLM-backed extractor (SuperDocs
itself could plausibly do this via `chat`, asked to locate and quote the clause) without touching anything
downstream - `ContractTerms` is the seam.

Every extracted value carries its exact source sentence as a quote, never a paraphrase - the whole point of
this build is that the governing clause is real and traceable, not assumed.
"""

from __future__ import annotations

import re

from app.models import ContractTerms

## `[^.]` (not `[^.\n]`) deliberately: a negated character class excludes only the literal period and
## already matches newlines regardless of re.DOTALL - a real contract wraps mid-sentence, and the first
## version of these patterns excluded '\n' explicitly, which silently failed to match a governing clause
## that happened to wrap onto a second line. Found by the test suite actually running against a
## multi-line sample contract, not by inspection - the sample text wasn't crafted to trigger this, it's
## just how the source document naturally wrapped.
##
## `(?:\d+\.\d+\s+)?` prefix - a second, more subtle bug in the same family, found during LIVE
## verification against the real SuperDocs API, not by inspection: every clause in this contract style is
## numbered "2.1", "2.2", "3.1" - and that section number itself contains a period. `[^.]*` correctly
## refuses to cross a REAL sentence-ending period, but it was equally refusing to cross the period INSIDE
## "3.1", so `.search()`'s leftmost-match behavior would skip past the section number entirely and start
## the quote from "1 If Customer..." instead of "3.1 If Customer...". All three quotes silently dropped
## their leading section number this way - existing tests never caught it because they only asserted
## substring containment, never the exact start of the quote. This prefix explicitly allows a leading
## "N.N " section number to include its own internal period before the no-bare-periods rule applies to
## the rest of the sentence.
_ENTITLEMENT_RE = re.compile(
    r"(?P<sentence>(?:\d+\.\d+\s+)?[^.]*entitled to use up to\s+([\d,]+(?:\.\d+)?)\s*\([^)]*\)[^.]*\.)",
    re.IGNORECASE,
)
_FEE_RE = re.compile(
    r"(?P<sentence>(?:\d+\.\d+\s+)?[^.]*fee for the Monthly Entitlement is\s+\$([\d,]+(?:\.\d+)?)[^.]*\.)",
    re.IGNORECASE,
)
_OVERAGE_RATE_RE = re.compile(
    r"(?P<sentence>(?:\d+\.\d+\s+)?[^.]*rate of\s+\$([\d,]+(?:\.\d+)?)\s*per[^.]*\.)",
    re.IGNORECASE,
)


class ClauseNotFoundError(Exception):
    """Raised when a required governing clause can't be confidently located - this is exactly one of the
    two conditions (app/exceptions.py) that makes a renewal a genuine exception rather than a guess."""

    def __init__(self, field_name: str):
        super().__init__(f"could not locate the '{field_name}' clause in the contract text")
        self.field_name = field_name


def _extract_number(pattern: re.Pattern, text: str, field_name: str) -> tuple[float, str]:
    match = pattern.search(text)
    if not match:
        raise ClauseNotFoundError(field_name)
    number_str = match.group(2).replace(",", "")
    return float(number_str), match.group("sentence").strip()


def extract_contract_terms(contract_text: str) -> ContractTerms:
    """Never partially succeeds silently: if any of the three governing facts can't be found, this raises
    ClauseNotFoundError rather than returning a ContractTerms with a guessed or zero value - a missing
    clause must surface as an exception, never as a quiet default (FR-equivalent of Task 1's 'never
    bluffs' principle, carried over as an engineering discipline, not shared code)."""
    entitlement, entitlement_quote = _extract_number(_ENTITLEMENT_RE, contract_text, "entitlement_units")
    fee, fee_quote = _extract_number(_FEE_RE, contract_text, "monthly_fee")
    rate, rate_quote = _extract_number(_OVERAGE_RATE_RE, contract_text, "overage_rate")
    return ContractTerms(
        entitlement_units=entitlement,
        entitlement_quote=entitlement_quote,
        monthly_fee=fee,
        fee_quote=fee_quote,
        overage_rate=rate,
        overage_rate_quote=rate_quote,
    )
