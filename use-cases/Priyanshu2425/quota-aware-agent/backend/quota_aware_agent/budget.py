"""BudgetGuard -- never start work you cannot finish.

SHARED CORE. This module is used unchanged by another system by the same
author, where it guards the publisher that writes documents back to SuperDocs.
It is vendored here rather than imported so this build stands alone in its own
repository. Reuse is only a shortcut when it is hidden, so it is stated here and
in the README.

Grounded in the SuperDocs documentation rather than in the task brief
(TASK.md rule 1). Two facts from the docs shape this module:

  * Most requests bill one operation; very large ones bill one per 25 sections
    edited. So pricing is done in sections and reported in operations.
  * The usage endpoints reject API keys -- `/v1/users/me/usage` and `/limits`
    accept web-app session tokens only. From an API-key context the balance is
    read off the `usage` block that rides on every chat response. You therefore
    learn your balance as a side effect of doing work, not in advance of it.

That second point is why `Balance` carries `authoritative`. Between calls the
number is an estimate and says so. `quota_exhausted` on a response is the
authoritative stop signal.

A SECOND ceiling exists when the build runs through the shared relay, which
lends the SuperDocs key under a ration of a few hundred operations per key per
day. It is modelled here rather than beside here, because "how many operations
may I spend?" already has an owner and a second answer to the same question
kept somewhere else is how a planner ends up sizing work against a number that
was never the binding one. So the ration is a `Balance` like any other, and
`remaining()` returns whichever ceiling is lower -- you may spend what BOTH
allow, and the report names which one is doing the stopping.

Its authority runs the other way round from the monthly allowance, and that is
the point of expressing it in the same vocabulary rather than as a counter. The
relay states nothing about the ration on a successful response, so a ration
number we are carrying is always `authoritative=False` -- an estimate, exactly
like the monthly number between calls. The one authoritative reading is the
refusal: `budget_exhausted` means it is gone, which is the same shape of fact as
`quota_exhausted` and reaches the planner the same way.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

SECTIONS_PER_OP = 25


@dataclass(frozen=True)
class Balance:
    ops: int
    authoritative: bool
    as_of: str = ""
    #: Which ceiling this number is, when it is not the account's own monthly
    #: allowance. Empty for the ordinary case, so nothing reads differently on
    #: the direct path -- a ceiling that is not in play must not be described.
    limited_by: str = ""

    def __str__(self) -> str:
        qualifier = "confirmed" if self.authoritative else "estimated"
        unit = "operation" if self.ops == 1 else "operations"
        capped = f", capped by {self.limited_by}" if self.limited_by else ""
        return f"{self.ops} {unit} ({qualifier}){capped}"


@dataclass(frozen=True)
class Change:
    row_id: str
    sections: int
    severity: str = "medium"


_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class Plan:
    publish: list[Change] = field(default_factory=list)
    defer: list[Change] = field(default_factory=list)
    rationale: str = ""
    #: How the published work will be sent -- one request, or one each. Carried
    #: on the plan so a price quoted at planning time and the price charged at
    #: run time cannot come from two different models of the same work.
    batched: bool = True

    @property
    def ops_to_publish(self) -> int:
        return estimate(self.publish, batched=self.batched)

    @property
    def complete(self) -> bool:
        return not self.defer


def estimate(changes: list[Change], *, batched: bool = True) -> int:
    """Operations a set of changes will bill.

    Zero changes cost nothing. Anything else costs at least one operation,
    then one more per 25 sections -- which is the documented accounting, not
    a division.

    `batched` is the question the docs force and that a section count alone
    cannot answer: **do these changes ride in one request, or in several?**
    The docs price a *request* -- "most requests bill one operation; very large
    ones bill one per 25 sections edited" -- so the floor of one applies per
    request, not per plan.

      * ``batched=True``  -- all of it goes in a single `POST /v1/chat/async`.
        That is the publisher's shape, where a document write is one call.
      * ``batched=False`` -- each change is its own call. That is the agent's
        shape: one edit instruction per step, one request each.

    Getting this wrong is not a rounding error. Four steps of five sections
    pooled to twenty sections price as ONE operation, and then bill as FOUR --
    so the agent reports "it fits", starts, and runs out partway through
    somebody's document. That is the exact failure this build exists to
    prevent, arriving through its own arithmetic.
    """
    if not batched:
        return sum(estimate([c]) for c in changes)
    sections = sum(c.sections for c in changes)
    if sections <= 0:
        return 0
    return max(1, math.ceil(sections / SECTIONS_PER_OP))


#: Said in one place so the planner, the report and the README cannot describe
#: the same ceiling differently.
RELAY_RATION = "the shared relay's daily ration"

#: The account's own ceiling, worded once. The exact sentence is asserted on by
#: the suite, because "why did it stop?" is the question this module exists to
#: answer and a reworded answer is a changed answer.
MONTHLY_EXHAUSTED = "the allowance is exhausted"


class BudgetGuard:
    def __init__(self, seed: Balance | None = None) -> None:
        self._balance = seed or Balance(ops=0, authoritative=False)
        #: The second ceiling, when there is one. None means the account's
        #: allowance is the only thing standing between us and the work.
        self._ration: Balance | None = None
        self._exhausted = False
        self._exhausted_because = ""

    # -- the second ceiling ------------------------------------------------
    def open_ration(self, ops: int, *, source: str = RELAY_RATION,
                    resets_at: str = "00:00 UTC") -> Balance:
        """Declare a daily ration sitting under the monthly allowance.

        Seeded `authoritative=False` from the first line: the ration is a
        published number, not a reading. Whoever lends it says how much it lends
        per day, never how much of today is left -- and part of a day's ration
        may already have gone to an earlier process on the same key. So this is
        a ceiling we hope is right, and it is labelled the way every other
        number we hope is right is labelled.
        """
        self._ration = Balance(max(0, ops), authoritative=False,
                               as_of=resets_at, limited_by=source)
        return self._ration

    def spend_ration(self, ops: int = 1) -> None:
        """One charged request has gone out.

        Counted in requests, not in the operations SuperDocs billed for them.
        The two genuinely differ: SuperDocs bills one operation per 25 sections
        edited, while the lender counts the calls it proxied. Deriving one from
        the other would be inventing an accounting rule neither party uses.
        """
        if self._ration is None:
            return
        self._ration = Balance(max(0, self._ration.ops - max(0, ops)),
                               authoritative=False, as_of=self._ration.as_of,
                               limited_by=self._ration.limited_by)

    def ration_exhausted(self, source: str = RELAY_RATION,
                         resets_at: str = "00:00 UTC") -> None:
        """The lender refused: today's ration is gone.

        The one authoritative fact about the ration, and it arrives the same way
        `quota_exhausted` does -- as a refusal, not as a reading -- so it is
        recorded the same way and stops the planner the same way. What differs
        is the remedy, which is why the reason is carried rather than a bare
        flag: waiting out a monthly quota and setting your own key are not the
        same advice.
        """
        self._ration = Balance(0, authoritative=True, as_of=resets_at,
                               limited_by=source)
        if not self._exhausted:
            # An account allowance that is genuinely gone is the harder stop and
            # keeps its explanation; the ration only speaks when it is the one
            # doing the stopping.
            self._exhausted_because = (
                f"{source} is spent for today and resets at {resets_at} -- the "
                "account's own allowance may well be untouched"
            )
        self._exhausted = True

    @property
    def ration(self) -> Balance | None:
        return self._ration

    @property
    def exhausted_because(self) -> str:
        """Which ceiling stopped us, in words. Empty when nothing has."""
        if not self._exhausted:
            return ""
        return self._exhausted_because or MONTHLY_EXHAUSTED

    def seed_from_whoami(self, remaining_ops: int, as_of: str = "") -> Balance:
        """The agent whoami call does accept an agent key, so this is the one
        moment the balance is genuinely authoritative before work begins."""
        self._balance = Balance(remaining_ops, authoritative=True, as_of=as_of)
        return self.remaining()

    def assume_spent(self, ops: int) -> Balance:
        """No usage block came back on a call we believe was billable.

        The docs say usage rides on every chat response; the async endpoints
        empirically return none (verified 2026-08-19). So the balance is
        decremented by our own estimate and, crucially, **stops being
        authoritative** -- continuing to print "confirmed" over a number the
        platform never confirmed is the exact bluff `authoritative` exists to
        prevent.
        """
        self._balance = Balance(
            max(0, self._balance.ops - max(0, ops)), authoritative=False,
            as_of=self._balance.as_of,
        )
        return self.remaining()

    def reconcile(self, ops_charged: int, monthly_remaining: int | None, quota_exhausted: bool,
                  as_of: str = "") -> Balance:
        """Called with the `usage` block from every response."""
        # `or` rather than `=`: a later free response saying the monthly quota
        # is fine must not un-say a ration refusal we already had in writing.
        # Two ceilings, and only the one that spoke gets to change its own mind.
        self._exhausted = quota_exhausted or self._ration_spent()
        if quota_exhausted:
            self._exhausted_because = MONTHLY_EXHAUSTED
        if monthly_remaining is not None:
            self._balance = Balance(monthly_remaining, authoritative=True, as_of=as_of)
        else:
            self._balance = Balance(
                max(0, self._balance.ops - ops_charged), authoritative=False, as_of=as_of
            )
        return self.remaining()

    def mark_exhausted(self) -> None:
        """The platform said so on a call that was allowed to complete anyway.

        Free calls are not refused when the allowance is gone, but the signal
        they carry is still the authoritative one and must reach the planner --
        otherwise the agent reads "exhausted" and plans as though it had not.
        """
        self._exhausted = True
        self._exhausted_because = MONTHLY_EXHAUSTED

    def _ration_spent(self) -> bool:
        return (self._ration is not None and self._ration.ops <= 0
                and self._ration.authoritative)

    def remaining(self) -> Balance:
        """What may actually be spent -- the lower of the ceilings in play.

        Not the account balance: a monthly allowance of 400 behind a daily
        ration of 12 is 12 operations of room, and reporting 400 to a planner
        that then sizes 40 steps to fit is the same failure this build exists to
        prevent, arriving through a number that was true about the wrong thing.
        """
        if self._ration is not None and self._ration.ops < self._balance.ops:
            return self._ration
        return self._balance

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    def fit(self, changes: list[Change], remaining: int | None = None,
            *, batched: bool = True) -> Plan:
        """Pure given a budget number. Publishes what fits, highest severity
        first, defers the rest, and says so in a sentence a person can read.

        `batched` says whether the published set is one request or one each;
        see `estimate`. It is threaded through rather than defaulted quietly,
        because a plan priced under the wrong model is a plan that fits on
        paper and overruns in practice.
        """
        budget = self.remaining().ops if remaining is None else remaining
        needed = estimate(changes, batched=batched)

        if self._exhausted or budget <= 0:
            # These are different situations and must not be reported as one.
            # "Exhausted" is a lender's own signal -- and WHICH lender, because
            # the remedies differ; a zero budget can also mean a reserve is
            # being held back so finished work stays usable.
            reason = (
                self.exhausted_because
                if self._exhausted
                else "there are no operations available to spend"
            )
            return Plan(
                publish=[],
                defer=list(changes),
                rationale=(
                    f"Started nothing: {reason}. "
                    f"{len(changes)} change(s) are queued and named in the run report."
                ),
                batched=batched,
            )

        if needed <= budget:
            return Plan(publish=list(changes), defer=[], rationale="", batched=batched)

        ordered = sorted(
            changes, key=lambda c: (_SEVERITY_ORDER.get(c.severity, 99), -c.sections)
        )
        publish: list[Change] = []
        for change in ordered:
            if estimate(publish + [change], batched=batched) <= budget:
                publish.append(change)
        deferred = [c for c in changes if c not in publish]

        pub_sections = sum(c.sections for c in publish)
        all_sections = sum(c.sections for c in changes)
        rationale = (
            f"Sized to fit: {pub_sections} of {all_sections} changed sections "
            f"({estimate(publish, batched=batched)} of {needed} operations). Deferred "
            f"{len(deferred)} lower-severity change(s) to stay inside the "
            "remaining allowance."
        )
        return Plan(publish=publish, defer=deferred, rationale=rationale,
                    batched=batched)
