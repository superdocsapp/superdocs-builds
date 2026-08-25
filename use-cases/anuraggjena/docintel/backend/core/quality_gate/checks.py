from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class CheckSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class CheckStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WARNING = "warning"


@dataclass
class CheckResult:
    check_name: str
    status: CheckStatus
    severity: CheckSeverity
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    blocking: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_name": self.check_name,
            "status": self.status.value,
            "severity": self.severity.value,
            "message": self.message,
            "details": self.details,
            "blocking": self.blocking,
        }


class BaseCheck(ABC):
    """Abstract base for quality gate checks."""

    name: str = ""
    severity: CheckSeverity = CheckSeverity.WARNING
    blocking: bool = False

    @abstractmethod
    async def run(self, state: Dict[str, Any], config: Dict[str, Any]) -> CheckResult:
        """Run the check against the workflow state."""
        ...

    def skip(self, reason: str) -> CheckResult:
        return CheckResult(
            check_name=self.name,
            status=CheckStatus.SKIPPED,
            severity=self.severity,
            message=reason,
            blocking=False,
        )

    def passed(self, message: str = "Check passed", details: Optional[Dict] = None) -> CheckResult:
        return CheckResult(
            check_name=self.name,
            status=CheckStatus.PASSED,
            severity=self.severity,
            message=message,
            details=details or {},
            blocking=False,
        )

    def failed(self, message: str, details: Optional[Dict] = None) -> CheckResult:
        return CheckResult(
            check_name=self.name,
            status=CheckStatus.FAILED,
            severity=self.severity,
            message=message,
            details=details or {},
            blocking=self.blocking,
        )

    def warning(self, message: str, details: Optional[Dict] = None) -> CheckResult:
        return CheckResult(
            check_name=self.name,
            status=CheckStatus.WARNING,
            severity=CheckSeverity.WARNING,
            message=message,
            details=details or {},
            blocking=False,
        )
