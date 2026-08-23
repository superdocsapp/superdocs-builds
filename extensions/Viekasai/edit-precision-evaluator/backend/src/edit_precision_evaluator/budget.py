from __future__ import annotations

from dataclasses import dataclass


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class OperationBudget:
    cap: int
    used: int = 0

    def __post_init__(self) -> None:
        if self.cap < 1:
            raise ValueError("Operation cap must be at least 1")

    @property
    def remaining(self) -> int:
        return self.cap - self.used

    def reserve(self, estimated_operations: int = 1) -> None:
        if estimated_operations < 1:
            raise ValueError("Estimated operations must be positive")
        if self.used + estimated_operations > self.cap:
            raise BudgetExceeded(
                f"Operation cap {self.cap} would be exceeded; "
                f"used={self.used}, requested={estimated_operations}"
            )
        self.used += estimated_operations

    def reconcile(self, reserved: int, actual: int | None) -> None:
        if actual is None:
            return
        if actual < 0:
            raise ValueError("Actual operation usage cannot be negative")
        self.used += actual - reserved
        if self.used > self.cap:
            raise BudgetExceeded(
                f"SuperDocs charged {actual} operations; actual usage {self.used} "
                f"exceeded the declared cap {self.cap}"
            )


def estimated_operations(case_count: int, approaches: set[str]) -> int:
    per_case = 0
    if "direct" in approaches:
        per_case += 1
    if "search_scoped" in approaches:
        per_case += 2  # one search/analysis call and one edit call
    return case_count * per_case
