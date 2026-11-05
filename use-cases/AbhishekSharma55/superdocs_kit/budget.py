"""A hard, persistent spending cap on SuperDocs operations.

Operations cost money and a free agent account gets 500 of them a month.
Anything in this repo that loops (52 weeks x 2 arms) can trivially burn
the lot, so the cap is not advisory:

* the cap is checked BEFORE a billable call, not after;
* every charge is appended to a JSONL ledger immediately, so a crash or a
  Ctrl-C mid-run cannot lose the record of money already spent;
* the ledger is the resume point - re-running a job skips work whose
  ledger entry already exists, which is what makes the runs idempotent;
* a stopping rule (``max_ops``) and a small-sample mode (``--weeks N``)
  exist from the first commit, not from the day we ran out.

Costs are read from the server's own ``usage.ops_charged``, never estimated.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import BudgetExceeded, QuotaExhausted


@dataclass
class Charge:
    ts: str
    label: str
    ops: int
    seconds: float
    monthly_used: int | None
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class OpsBudget:
    """Append-only ledger + hard cap.

    Usage:
        budget = OpsBudget(Path("out/ledger.jsonl"), max_ops=120)
        budget.check("week-07")            # raises BEFORE you spend
        ...call the API...
        budget.record("week-07", response, seconds)
    """

    def __init__(
        self,
        ledger_path: Path,
        max_ops: int,
        *,
        reserve: int = 0,
        label_prefix: str = "",
    ) -> None:
        self.path = Path(ledger_path)
        self.max_ops = int(max_ops)
        self.reserve = int(reserve)
        self.label_prefix = label_prefix
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.charges: list[Charge] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.charges.append(Charge(**json.loads(line)))

    # ---- reading ---------------------------------------------------
    @property
    def spent(self) -> int:
        return sum(c.ops for c in self.charges)

    @property
    def remaining(self) -> int:
        return self.max_ops - self.spent - self.reserve

    def done_labels(self) -> set[str]:
        """Labels already charged. The resume point."""
        return {c.label for c in self.charges}

    def already_done(self, label: str) -> bool:
        return self._full(label) in self.done_labels()

    # ---- writing ---------------------------------------------------
    def check(self, label: str, expected: int = 1) -> None:
        if self.remaining < expected:
            raise BudgetExceeded(
                f"'{label}' needs ~{expected} op(s) but only {self.remaining} remain "
                f"under the local cap of {self.max_ops} (spent {self.spent}).",
                "Re-run with a higher --max-ops, or with a smaller --weeks sample. "
                f"Work already completed is in {self.path} and will not be repeated.",
            )

    def record(self, label: str, response: Any, seconds: float, note: str = "") -> int:
        """Record what the SERVER says this call cost. Returns ops charged."""
        usage = {}
        if isinstance(response, dict):
            usage = response.get("usage") or (response.get("result") or {}).get("usage") or {}
        ops = usage.get("ops_charged")
        if ops is None:
            ops = 1 if usage.get("was_billable") else 0
        if usage.get("quota_exhausted"):
            self._append(Charge(_now(), self._full(label), int(ops), seconds,
                                usage.get("monthly_used"), note="quota_exhausted"))
            raise QuotaExhausted(
                "The SuperDocs account has no billable operations left this cycle.",
                "Redeem a promo code or upgrade at use.superdocs.app (Settings -> Billing), "
                "or wait for the cycle reset. Completed work is already on disk.",
            )
        charge = Charge(_now(), self._full(label), int(ops), round(seconds, 3),
                        usage.get("monthly_used"), note)
        self._append(charge)
        return int(ops)

    def record_free(self, label: str, seconds: float, note: str = "") -> None:
        """Log a non-billable call (exports, downloads, polls) so the timing
        record is complete even though the money record is zero."""
        self._append(Charge(_now(), self._full(label), 0, round(seconds, 3), None, note))

    def _append(self, charge: Charge) -> None:
        with self._lock:
            self.charges.append(charge)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(charge.as_dict(), ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())  # survive a kill -9, not just a clean exit

    def _full(self, label: str) -> str:
        return f"{self.label_prefix}{label}" if self.label_prefix else label

    def summary(self) -> dict[str, Any]:
        billable = [c for c in self.charges if c.ops > 0]
        return {
            "calls": len(self.charges),
            "billable_calls": len(billable),
            "ops_spent": self.spent,
            "cap": self.max_ops,
            "remaining": self.remaining,
            "wall_seconds": round(sum(c.seconds for c in self.charges), 1),
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
