"""Value normalisation primitives shared by every engine.

Keeping parsing of money/percent/date in one place means the arithmetic engine,
the date engine and fact extraction all agree on what a value *is* — the single
most common source of false positives in document auditing.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from dateutil import parser as date_parser

CURRENCY_SYMBOLS = {
    "$": "USD",
    "US$": "USD",
    "₹": "INR",
    "Rs.": "INR",
    "Rs": "INR",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
}

_SCALE_WORDS = {
    "k": Decimal(1_000),
    "thousand": Decimal(1_000),
    "lakh": Decimal(100_000),
    "lakhs": Decimal(100_000),
    "m": Decimal(1_000_000),
    "mn": Decimal(1_000_000),
    "million": Decimal(1_000_000),
    "crore": Decimal(10_000_000),
    "crores": Decimal(10_000_000),
    "bn": Decimal(1_000_000_000),
    "billion": Decimal(1_000_000_000),
}

MONEY_RE = re.compile(
    r"(?P<symbol>US\$|Rs\.?|[$₹€£¥])\s?(?P<number>-?\d[\d,\.\s]*\d|\d)"
    r"(?:\s?(?P<scale>k|thousand|lakhs?|mn?|million|crores?|bn|billion))?"
    r"|(?P<number2>-?\d[\d,]*(?:\.\d+)?)\s?(?P<code>USD|INR|EUR|GBP|JPY)"
    r"|(?P<code2>USD|INR|EUR|GBP|JPY)\s?(?P<number3>-?\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)

PERCENT_RE = re.compile(r"(?P<number>-?\d+(?:\.\d+)?)\s?%")

DATE_RE = re.compile(
    r"\b("
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+\d{4}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)

NUMBER_RE = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?![\w%])")


def to_decimal(raw: str) -> Decimal | None:
    """Parse a human-written number. Handles thousands separators and (1,234)
    accounting negatives, and rejects ambiguous garbage instead of guessing."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace(",", "").replace(" ", "")
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return -value if negative else value


def parse_money(text: str) -> dict | None:
    """Return {amount, currency, raw} for the first monetary value found."""
    match = MONEY_RE.search(text or "")
    if not match:
        return None
    if match.group("number2") or match.group("number3"):
        amount = to_decimal(match.group("number2") or match.group("number3"))
        currency = (match.group("code") or match.group("code2") or "").upper()
        scale = None
    else:
        amount = to_decimal(match.group("number"))
        symbol = (match.group("symbol") or "").strip()
        currency = CURRENCY_SYMBOLS.get(symbol, CURRENCY_SYMBOLS.get(symbol.rstrip("."), "UNKNOWN"))
        scale = (match.group("scale") or "").lower() or None
    if amount is None:
        return None
    if scale:
        amount = amount * _SCALE_WORDS[scale]
    return {
        "amount": float(amount),
        "currency": currency or "UNKNOWN",
        "raw": match.group(0).strip(),
        "scaled": bool(scale),
    }


def parse_percentage(text: str) -> dict | None:
    match = PERCENT_RE.search(text or "")
    if not match:
        return None
    value = to_decimal(match.group("number"))
    if value is None:
        return None
    return {"value": float(value), "fraction": float(value) / 100.0, "raw": match.group(0)}


def parse_date(text: str, *, dayfirst: bool = True) -> dict | None:
    """Parse a date and record the ambiguity that caused the interpretation.

    `ambiguous` matters: 03/04/2025 means different things in different
    locales, and silently picking one is exactly the sort of invisible
    assumption that produces wrong audit findings.
    """
    match = DATE_RE.search(text or "")
    if not match:
        return None
    raw = match.group(0)
    try:
        parsed = date_parser.parse(raw, dayfirst=dayfirst, fuzzy=False).date()
    except (ValueError, OverflowError):
        return None

    ambiguous = False
    numeric = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", raw)
    if numeric:
        first, second = int(numeric.group(1)), int(numeric.group(2))
        ambiguous = first <= 12 and second <= 12 and first != second

    return {
        "iso_date": parsed.isoformat(),
        "raw": raw,
        "ambiguous": ambiguous,
        "assumed_dayfirst": dayfirst,
    }


def iso_to_date(value: str | date | None) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def close_enough(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance


def format_money(amount: float, currency: str | None = None) -> str:
    formatted = f"{amount:,.2f}"
    return f"{currency} {formatted}".strip() if currency and currency != "UNKNOWN" else formatted
