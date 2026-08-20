"""Money, and the recogniser that decides what counts as one.

The recogniser is deliberately narrow, and it is narrow for the same reason the
ingester's was (PROGRESS.md 2026-08-08, Assumption 13): a token is a figure only
if it is thousands-grouped (Indian grouping included, so `50,00,000` works) or
written to exactly two decimals. That excludes bare years, pin codes, survey
numbers, the CIN, plain counts and bare percentages.

It has to be narrow in both directions here. Too wide and the year in "31 March
2026" becomes a figure that must be cited; too narrow and a figure slips into
the document without provenance, which is the one thing INVARIANTS.md item 6
exists to prevent. Both directions are tested.
"""

from __future__ import annotations

import html as _html
import re
from decimal import Decimal, InvalidOperation

# Grouped (2,180.00 / 50,00,000 / 42,000) or exactly two decimals (0.00 / 8.14).
# Brackets are the accounting negative.
# Brackets are matched as a *pair* or not at all. An optional bracket on each
# side independently reads "(703.00 + 87.00)" as the token "(703.00", which is
# a bracket belonging to the sentence - the exact silent-skip we caught in
# Phase 3 (PROGRESS.md 2026-08-09). Bracketed alternatives come first so the
# accounting negative wins where both could match.
_MONEY = re.compile(
    r"\(\d{1,3}(?:,\d{2,3})+(?:\.\d{2})?\)"  # bracketed, thousands-grouped
    r"|\(\d+\.\d{2}\)"  # bracketed, two decimals
    r"|\d{1,3}(?:,\d{2,3})+(?:\.\d{2})?"  # thousands-grouped
    r"|\d+\.\d{2}"  # exactly two decimals
)
_TAG = re.compile(r"<[^>]*>")


def format_money(value: Decimal) -> str:
    """Accounting presentation: grouped to two decimals, negatives in brackets."""
    q = Decimal(value).quantize(Decimal("0.01"))
    if q == 0:
        # A nil balance carried through a presentation sign flip is Decimal("-0.00"),
        # which formats as "-0.00" and reads as a figure nobody wrote.
        q = abs(q)
    if q < 0:
        return f"({-q:,.2f})"
    return f"{q:,.2f}"


def parse_money(token: str) -> Decimal:
    """Inverse of `format_money` for a single recognised token."""
    text = token.strip()
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace(",", "")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - guarded by the recogniser
        raise ValueError(f"not a money token: {token!r}") from exc
    return -value if negative else value


def strip_markup(fragment: str) -> str:
    """Tag-free text of an HTML fragment, entities resolved.

    The scan runs over text, never over markup: a chunk id is a hex string and a
    style rule is full of numbers, and neither is a figure anybody wrote.
    """
    return _html.unescape(_TAG.sub(" ", fragment))


def money_tokens(text: str) -> list[str]:
    """Every money token in plain text, in order of appearance.

    A match is rejected when it is glued to more digits (so a longer number is
    never read as a short one) or immediately followed by `%` (so `9.15%` is a
    rate, not 9.15 lakhs).
    """
    found: list[str] = []
    for match in _MONEY.finditer(text):
        start, end = match.span()
        before = text[start - 1] if start else ""
        after = text[end] if end < len(text) else ""
        if before.isdigit() or before in {",", "."}:
            continue
        if after.isdigit() or after == "%":
            continue
        found.append(match.group(0))
    return found


def money_tokens_in_html(fragment: str) -> list[str]:
    return money_tokens(strip_markup(fragment))
