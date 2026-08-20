"""Operation budget guard: ledger, cap enforcement, and honest spend reporting.

Edits and auto-judging bill operations; uploads, approvals, exports, and reads
do not. The guard refuses to start a billable call that would exceed the cap,
records every response's usage delta, and produces the spend report the study
commits to publishing.
"""

import json
import time
from pathlib import Path
from typing import Optional

from . import config


class BudgetExceeded(RuntimeError):
    pass


class BudgetGuard:
    def __init__(self, cap_ops: Optional[int] = None, ledger_path: Optional[Path] = None):
        self.cap_ops = cap_ops if cap_ops is not None else config.DEFAULT_BUDGET_CAP_OPS
        self.ledger_path = ledger_path or config.LEDGER_PATH
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._session_spend = 0

    def guard(self, estimated_ops: int = 1) -> None:
        spent = self.spend_this_process()
        if spent + estimated_ops > self.cap_ops:
            raise BudgetExceeded(
                f"budget cap {self.cap_ops} ops would be exceeded "
                f"(spent {spent}, need {estimated_ops}+)"
            )

    def record(self, resp: dict, endpoint: str = "", tag: str = "") -> dict:
        from .superdocs_client import parse_usage

        usage = parse_usage(resp)
        ops = int(usage.get("ops_charged", 0) or (1 if usage.get("was_billable") else 0))
        entry = {
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "endpoint": endpoint,
            "tag": tag,
            "was_billable": usage.get("was_billable", False),
            "ops_charged": ops,
            "monthly_remaining": usage.get("monthly_remaining"),
            "monthly_used": usage.get("monthly_used"),
        }
        with self.ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        self._session_spend += ops
        return entry

    def spend_this_process(self) -> int:
        return self._session_spend

    def load_ledger(self) -> list[dict]:
        if not self.ledger_path.exists():
            return []
        rows = []
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows

    def total_spend(self) -> int:
        return sum(int(r.get("ops_charged", 0)) for r in self.load_ledger())

    def report(self) -> dict:
        rows = self.load_ledger()
        billable = [r for r in rows if r.get("was_billable")]
        return {
            "cap_ops": self.cap_ops,
            "spent_ops": sum(int(r.get("ops_charged", 0)) for r in rows),
            "billable_calls": len(billable),
            "total_calls_recorded": len(rows),
            "remaining_within_cap": max(0, self.cap_ops - sum(int(r.get("ops_charged", 0)) for r in rows)),
            "entries": rows,
        }