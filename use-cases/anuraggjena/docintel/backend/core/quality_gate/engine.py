from typing import Any, Dict, List, Type
from dataclasses import dataclass

from backend.core.quality_gate.checks import BaseCheck, CheckResult, CheckStatus
from backend.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class GateResult:
    status: str  # passed, failed, warning, skipped
    checks_run: int
    checks_passed: int
    checks_failed: int
    blocking: bool
    results: List[CheckResult]

    def to_details(self) -> List[Dict]:
        return [r.to_dict() for r in self.results]


class QualityGateEngine:
    """Runs a list of quality checks against workflow state."""

    def __init__(self):
        self._checks: List[BaseCheck] = []

    def register(self, check: BaseCheck) -> None:
        self._checks.append(check)

    def register_many(self, checks: List[BaseCheck]) -> None:
        for check in checks:
            self.register(check)

    async def run(
        self,
        state: Dict[str, Any],
        config: Dict[str, Any],
        enabled_checks: List[str] | None = None
    ) -> GateResult:
        """Run all registered checks. If enabled_checks is provided, only run those."""
        checks_to_run = self._checks
        if enabled_checks is not None:
            checks_to_run = [c for c in self._checks if c.name in enabled_checks]

        if not checks_to_run:
            return GateResult(
                status="skipped",
                checks_run=0,
                checks_passed=0,
                checks_failed=0,
                blocking=False,
                results=[]
            )

        results: List[CheckResult] = []
        for check in checks_to_run:
            check_config = config.get(check.name, {})
            try:
                result = await check.run(state, check_config)
                results.append(result)
                logger.info("quality_check_run", check=check.name, status=result.status.value)
            except Exception as e:
                logger.error("quality_check_error", check=check.name, error=str(e))
                results.append(check.failed(f"Check raised exception: {e}"))

        passed = sum(1 for r in results if r.status == CheckStatus.PASSED)
        failed = sum(1 for r in results if r.status in (CheckStatus.FAILED,))
        blocking = any(r.blocking for r in results if r.status == CheckStatus.FAILED)

        if failed == 0:
            status = "warning" if any(r.status == CheckStatus.WARNING for r in results) else "passed"
        else:
            status = "failed"

        return GateResult(
            status=status,
            checks_run=len(results),
            checks_passed=passed,
            checks_failed=failed,
            blocking=blocking,
            results=results
        )
