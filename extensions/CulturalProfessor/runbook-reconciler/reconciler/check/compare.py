"""Deciding whether two ways of saying a number are the same number.

This is where most of the real difficulty of the deterministic layer lives, and
almost all of it is units. A Prometheus histogram is in seconds and a runbook is
written in milliseconds. A ratio is `0.05` in an expression and `5%` in a
sentence. A staleness threshold is `1800` in one place and "30 minutes" in the
other. All three pairs are equal, and a comparator that reports them as drift is
worse than useless: it produces three confident findings on a page with nothing
wrong with it, and after the second one nobody reads the third.

The rule when a conversion is not available is the same as everywhere else in
this project: **return `None` and let the caller record `unverifiable`.** A
comparison that cannot be made honestly is not a comparison that should be
guessed at.

`unit_hint` comes from the observation's context — usually the alerting
expression itself, because `http_request_duration_seconds_bucket` says what unit
the threshold beside it is in, and nothing else does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")
# `(?!\w)` and not `\b`: a word boundary after `%` requires a word character on
# one side of it, so `5%` matched with the unit group empty and the percentage
# was compared against `0.05` as a bare 5. Two pages of the corpus reported drift
# on a threshold that was correct.
_UNIT = re.compile(
    r"(?P<number>-?\d+(?:[.,]\d+)?)\s*(?P<unit>ms|s|%|jobs|messages|times|"
    r"seconds?|minutes?|hours?|days?|d|h|m)?(?!\w)",
    re.IGNORECASE,
)
_CRON = re.compile(r"cron\((?P<minute>\d+)\s+(?P<hour>\d+)\s")
_CLOCK = re.compile(r"(?P<hour>\d{1,2}):(?P<minute>\d{2})")

_TO_SECONDS = {
    "ms": 0.001,
    "s": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "m": 60.0,
    "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hour": 3600.0,
    "hours": 3600.0,
    "d": 86400.0,
    "day": 86400.0,
    "days": 86400.0,
}


@dataclass(frozen=True)
class Quantity:
    number: float
    unit: str | None

    @property
    def seconds(self) -> float | None:
        factor = _TO_SECONDS.get((self.unit or "").lower())
        return self.number * factor if factor else None


def parse_quantity(text: str) -> Quantity | None:
    match = _UNIT.search(text.strip())
    if not match:
        return None
    number = float(match.group("number").replace(",", ""))
    unit = match.group("unit")
    return Quantity(number, unit.lower() if unit else None)


def compare(kind: str, asserted: str, observed: str, hint: dict | None = None) -> bool | None:
    """`True` agrees, `False` contradicts, `None` could not be decided.

    The third case is the one that matters. Every caller turns it into
    `unverifiable`, which is reported and counted rather than being quietly
    rounded to either of the other two.
    """
    hint = hint or {}
    if kind == "text":
        return asserted.strip().lower() == observed.strip().lower()
    if kind == "exists":
        return True  # the lookup found it; existence was the whole question
    if kind == "numeric":
        return _numeric(asserted, observed, str(hint.get("expr", "")))
    if kind == "duration":
        return _duration(asserted, observed, hint)
    if kind == "window":
        return _window(asserted, hint)
    if kind == "clock":
        return _clock(asserted, observed)
    return None


def _numeric(asserted: str, observed: str, expr: str) -> bool | None:
    left, right = parse_quantity(asserted), parse_quantity(observed)
    if left is None or right is None:
        return None

    # Percentages. A rate expression compares against a fraction; the runbook
    # writes the same value as a percentage, and both are correct.
    if left.unit == "%":
        return _close(left.number / 100.0, right.number) or _close(left.number, right.number)

    # Time. The expression names its own unit -- `_seconds` in a metric name is
    # the only reliable statement of it anywhere in a Prometheus estate.
    if "_seconds" in expr or "time()" in expr:
        left_seconds = left.seconds
        if left_seconds is not None:
            return _close(left_seconds, right.number)

    if left.unit in ("ms", "s", "minutes", "minute", "hours", "hour") and right.unit is None:
        # A unit on one side and none on the other, with nothing in the
        # expression to say what the bare number means. Guessing here is how a
        # correct page gets reported as drift.
        return None

    return _close(left.number, right.number)


def _duration(asserted: str, observed: str, hint: dict) -> bool | None:
    left = parse_quantity(asserted)
    if left is None or left.seconds is None:
        return None
    right_seconds = hint.get("seconds")
    if right_seconds is None:
        right = parse_quantity(observed)
        if right is None:
            return None
        # `backup_retention_period = 14` is a bare number in the file and
        # fourteen days in the world. The unit is not recoverable from the value
        # and is not guessed: the rule that points at the attribute declares it,
        # and without that declaration this stays unverifiable.
        unit = right.unit or hint.get("observed_unit")
        right_seconds = Quantity(right.number, unit).seconds
    if right_seconds is None:
        return None
    return _close(left.seconds, float(right_seconds))


def _window(asserted: str, hint: dict) -> bool | None:
    """Does the stated window match any range selector in the expression?

    Any, not all: `sum(rate(x[30m])) / sum(rate(y[30m]))` has two and a runbook
    describing "a 30 minute window" is right about both.
    """
    left = parse_quantity(asserted)
    if left is None or left.seconds is None:
        return None
    ranges = hint.get("ranges") or []
    for selector in ranges:
        right = parse_quantity(selector)
        if right and right.seconds is not None and _close(left.seconds, right.seconds):
            return True
    return False


def _clock(asserted: str, observed: str) -> bool | None:
    """ "03:00 UTC daily" against `cron(0 3 * * ? *)`.

    Two notations for one time of day, and a DR document is very likely to
    disagree with the schedule that actually runs. No timezone arithmetic: cron
    schedules in AWS Backup are UTC and the document says UTC, and a comparator
    that quietly assumed otherwise would be inventing a fact.
    """
    cron = _CRON.search(observed)
    clock = _CLOCK.search(asserted)
    if not cron or not clock:
        return None
    return (int(cron.group("hour")), int(cron.group("minute"))) == (
        int(clock.group("hour")),
        int(clock.group("minute")),
    )


def _close(left: float, right: float) -> bool:
    """Equality for numbers that arrived as text.

    A relative tolerance, because `0.05` and `5%` do not round-trip exactly
    through floating point and a checker that reports that as drift would be
    right about the arithmetic and wrong about the world.
    """
    return abs(left - right) <= max(1e-9, abs(right) * 1e-9)


__all__ = ["Quantity", "compare", "parse_quantity"]
