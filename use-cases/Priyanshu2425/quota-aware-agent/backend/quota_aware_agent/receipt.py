"""What a run actually spent, line by line, and whether that adds up.

From the research, an engineer describing what they did after a job died
halfway: *"I added it up from the responses I'd logged, and it didn't match the
number in the account, so I stopped looking."*

Two failures in one sentence. They had to do the arithmetic by hand, and when
the arithmetic disagreed with the platform there was nothing to tell them which
side was wrong — so the disagreement went uninvestigated. A receipt does the
adding up, and `reconcile` does the comparison and **names the disagreement
instead of hiding it**.

The one rule this module refuses to break: a number the platform did not state
is never presented as one it did. An operation charged is what a `usage` block
said; an operation *estimated* is what we believed. They are separate columns,
they are never summed together, and a receipt whose balances were not
authoritative says the reconciliation could not be done rather than doing it on
guesses.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from .budget import Balance


@dataclass(frozen=True)
class Line:
    """One call, and what it cost."""

    step_id: str
    call: str
    billable: bool
    #: What the platform's `usage` block said it charged. None when no usage
    #: block came back, which is not the same as zero.
    ops_charged: int | None = None
    #: What we believed it would cost, before it happened.
    ops_estimated: int = 0
    balance_after: int | None = None
    balance_authoritative: bool = False
    note: str = ""

    @property
    def counted(self) -> int:
        """Only what the platform stated. Never the estimate."""
        return self.ops_charged or 0


@dataclass(frozen=True)
class Reconciliation:
    checkable: bool
    agrees: bool
    counted: int
    implied: int | None
    explanation: str


@dataclass
class Receipt:
    """The line items of one run, in the order they happened."""

    session_id: str = ""
    lines: list[Line] = field(default_factory=list)

    def record(self, step_id: str, call: str, *, billable: bool,
               ops_charged: int | None = None, ops_estimated: int = 0,
               balance: Balance | None = None, note: str = "") -> Line:
        line = Line(
            step_id=step_id, call=call, billable=billable,
            ops_charged=ops_charged, ops_estimated=ops_estimated,
            balance_after=balance.ops if balance else None,
            balance_authoritative=bool(balance and balance.authoritative),
            note=note,
        )
        self.lines.append(line)
        return line

    # -- what it adds up to ------------------------------------------------
    @property
    def counted(self) -> int:
        """Operations the platform said it charged."""
        return sum(l.counted for l in self.lines)

    @property
    def estimated_only(self) -> int:
        """Operations we believe were charged on calls that reported nothing.

        Kept apart from `counted` on purpose. Adding them would produce one
        number that is part measurement and part belief, and nobody downstream
        could tell which part.
        """
        return sum(l.ops_estimated for l in self.lines
                   if l.billable and l.ops_charged is None)

    @property
    def billable_calls(self) -> int:
        return sum(1 for l in self.lines if l.billable)

    @property
    def unreported_billable_calls(self) -> int:
        return sum(1 for l in self.lines if l.billable and l.ops_charged is None)

    def reconcile(self, start: Balance | None, end: Balance | None) -> Reconciliation:
        """Does what the lines add up to match what the balance moved by?

        Only checkable when both ends of the run were *authoritative*. An
        estimate on either end makes the difference an estimate too, and a
        reconciliation between two guesses is theatre.
        """
        counted = self.counted
        if start is None or end is None:
            return Reconciliation(
                False, False, counted, None,
                "There is no starting or ending balance to compare against.")
        if not (start.authoritative and end.authoritative):
            which = []
            if not start.authoritative:
                which.append("the starting balance")
            if not end.authoritative:
                which.append("the ending balance")
            return Reconciliation(
                False, False, counted, None,
                f"{' and '.join(which).capitalize()} was inferred rather than "
                "stated by the platform, so this run cannot be reconciled. "
                f"{counted} operation(s) were confirmed charged"
                + (f", and {self.estimated_only} more were estimated on calls "
                   "that reported no usage." if self.estimated_only else "."),
            )

        implied = start.ops - end.ops
        if implied == counted:
            return Reconciliation(
                True, True, counted, implied,
                f"{counted} operation(s) charged, and the allowance moved by "
                f"{implied}. These agree.")
        gap = implied - counted
        return Reconciliation(
            True, False, counted, implied,
            f"The line items add up to {counted} operation(s), but the allowance "
            f"moved by {implied}. That is a difference of {gap}. It is reported "
            "rather than reconciled away: something was charged that this run "
            "did not record, or something else is spending against the same "
            "account.",
        )

    # -- handing it over ---------------------------------------------------
    def as_dict(self, start: Balance | None = None,
                end: Balance | None = None) -> dict:
        rec = self.reconcile(start, end)
        return {
            "session_id": self.session_id,
            "lines": [asdict(l) for l in self.lines],
            "billable_calls": self.billable_calls,
            "operations_charged": self.counted,
            "operations_estimated_only": self.estimated_only,
            "calls_that_reported_no_usage": self.unreported_billable_calls,
            "reconciliation": asdict(rec),
        }

    def as_json(self, start: Balance | None = None,
                end: Balance | None = None) -> str:
        return json.dumps(self.as_dict(start, end), indent=2)

    def render_text(self, start: Balance | None = None,
                    end: Balance | None = None) -> str:
        out = ["RUN RECEIPT" + (f" · {self.session_id}" if self.session_id else ""),
               "=" * 62]
        if start:
            out.append(f"Allowance at the start: {start}")
        out.append("")
        out.append(f"{'STEP':<18}{'CALL':<12}{'CHARGED':>9}{'LEFT':>9}")
        out.append("-" * 62)
        for l in self.lines:
            charged = "—" if l.ops_charged is None else str(l.ops_charged)
            if l.ops_charged is None and l.billable:
                charged = f"~{l.ops_estimated}"
            left = "—" if l.balance_after is None else (
                str(l.balance_after) + ("" if l.balance_authoritative else "?"))
            out.append(f"{l.step_id[:17]:<18}{l.call[:11]:<12}{charged:>9}{left:>9}")
            if l.note:
                out.append(f"  {l.note}")
        out.append("-" * 62)
        out.append(f"{'confirmed charged':<30}{self.counted:>9}")
        if self.estimated_only:
            out.append(f"{'estimated, never confirmed':<30}{self.estimated_only:>9}")
        if end:
            out.append(f"Allowance at the end: {end}")
        out.append("")
        rec = self.reconcile(start, end)
        out.append("DOES IT ADD UP?")
        out.append("-" * 62)
        out.append(rec.explanation)
        out.append("")
        out.append("A '~' is an operation we believe was charged on a call that "
                   "returned no usage")
        out.append("block. A '?' is a balance we inferred rather than one the "
                   "platform stated.")
        return "\n".join(out)
