"""A hard stop on what a run may spend.

Operations cost money, and a long job is exactly the shape of thing that can spend a
month's allowance while nobody is watching. So spend is bounded twice, and the run stops
cleanly at whichever bound it reaches first:

* **A per-run ceiling** the operator sets, so one job cannot consume an allowance meant
  for a week of work.
* **A floor under the account's own remaining balance**, read from what the server reports
  after every turn. This is the one that matters, because it is ground truth rather than
  local arithmetic — if something else spent the allowance while this run was working, the
  run finds out on its next turn and stops.

Stopping is not failing. The run halts before issuing the turn it cannot afford, reports
``blocked`` with the reason, and resumes later from exactly that step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class BudgetExhausted(Exception):
    """The next turn would spend past a limit. Raised before it is issued, never after."""


@dataclass
class OperationBudget:
    """Tracks billable operations and refuses to cross a line.

    ``limit`` is what this invocation may spend. ``reserve`` is how many operations must
    remain on the account afterwards — headroom deliberately left for someone else.
    """

    limit: int | None = None
    reserve: int = 0
    spent: int = 0
    account_remaining: int | None = None
    account_limit: int | None = None

    def check(self) -> None:
        """Raise if the *next* turn would cross a line. Called before issuing, not after."""
        if self.limit is not None and self.spent >= self.limit:
            raise BudgetExhausted(
                f"this run has spent its budget of {self.limit} operations "
                f"({self.spent} used). Raise --max-operations to continue; the run "
                f"resumes from this step and repeats nothing."
            )
        if self.account_remaining is not None and self.account_remaining <= self.reserve:
            raise BudgetExhausted(
                f"the account has {self.account_remaining} operations left and "
                f"--reserve is {self.reserve}. Stopping here rather than spending into "
                f"the reserve; the run resumes from this step and repeats nothing."
            )

    def record(self, job: Any) -> int:
        """Take the server's word for what a turn cost, and for what is left.

        Longhaul keeps no opinion about pricing: a turn that changed nothing, failed, or
        was denied is not billed, and only the server knows which happened.
        """
        result = getattr(job, "result", None) or {}
        usage = result.get("usage") or {}
        if usage.get("was_billable"):
            self.spent += 1
        remaining = usage.get("monthly_remaining")
        if isinstance(remaining, int):
            self.account_remaining = remaining
        monthly_limit = usage.get("monthly_limit")
        if isinstance(monthly_limit, int):
            self.account_limit = monthly_limit
        return self.spent

    def describe(self) -> str:
        parts = [f"{self.spent} operation{'s' if self.spent != 1 else ''} spent"]
        if self.limit is not None:
            parts.append(f"of {self.limit} allowed this run")
        if self.account_remaining is not None:
            parts.append(f"{self.account_remaining} left on the account")
        return ", ".join(parts)
