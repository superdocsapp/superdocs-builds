"""Derived facts — the ones the pack can compute rather than ask about.

Florida's radon disclosure turns on whether the lease term exceeds 45 days.
Asking a user to type `lease_term_days` when they have already given a start and
an end date would be asking them to do arithmetic the tool can do, and every
hand-entered number is a number that can be entered wrong.

So derived facts are computed here and layered *under* the user's own answers: an
explicit entry in `disclosure_facts` always wins. That ordering matters. A
coordinator who knows the term is being extended can override the derived value,
and the override is visible in their input file rather than buried in code.

A derived fact that cannot be computed (an unparseable date, a missing end date)
is simply absent, which flows back into the same UNDETERMINED path as any other
unanswered fact — it never silently becomes zero.
"""
from __future__ import annotations

from typing import Any

from .models import UNSET, LeasePackRequest


def derive_facts(req: LeasePackRequest) -> dict[str, Any]:
    """Facts computable from what the user already supplied.

    Deliberately only what a shipped rule actually asks for. Earlier versions
    also derived `is_pre_1978` and `is_pre_1960`, which looked useful and were
    referenced by nothing: the rules that care about construction year express it
    directly as `year_built < 1978`, which reads better in the rule file than a
    pre-computed flag whose threshold is hidden in Python. Derived facts are a
    place where speculative helpers accumulate, so the bar is that something asks
    for it.
    """
    derived: dict[str, Any] = {}

    # Florida's radon notice turns on a lease term longer than 45 days. The dates
    # are already on the record, so asking a user to do that subtraction would
    # only be an opportunity to get it wrong.
    start = req.tenancy.parsed_start()
    end = req.tenancy.parsed_end()
    if start is not None and end is not None and end >= start:
        derived["lease_term_days"] = (end - start).days

    return derived


class FactView:
    """A `LeasePackRequest` with derived facts layered underneath.

    Implements the same `lookup_fact` contract the condition engine expects, so
    rules cannot tell the difference between a fact the user typed and one the
    pack worked out — which is the point.
    """

    def __init__(self, req: LeasePackRequest):
        self.request = req
        self.derived = derive_facts(req)

    def lookup_fact(self, name: str) -> Any:
        value = self.request.lookup_fact(name)
        if value is not UNSET:
            return value
        if name in self.derived:
            derived_value = self.derived[name]
            return UNSET if derived_value is None else derived_value
        return UNSET

    def is_derived(self, name: str) -> bool:
        """True when a fact came from computation rather than from the user.
        Used by `pack facts` so nobody is asked to supply something already known."""
        return name in self.derived and self.request.lookup_fact(name) is UNSET
