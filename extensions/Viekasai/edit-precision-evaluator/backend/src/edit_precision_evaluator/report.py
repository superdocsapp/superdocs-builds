from __future__ import annotations

from collections import defaultdict
from statistics import mean

from .models import RunResult


def _summary(results: list[RunResult]) -> dict:
    return {
        "cases": len(results),
        "intended_change_coverage": round(
            mean(item.score.intended_change_coverage for item in results), 6
        ),
        "collateral_damage_rate": round(
            mean(item.score.collateral_damage_rate for item in results), 6
        ),
        "precision_loss": round(mean(item.score.precision_loss for item in results), 6),
        "latency_ms": round(mean(item.latency_ms for item in results)),
        "operations_used": sum(item.operations_used for item in results),
    }


def build_report(results: list[RunResult], *, operation_cap: int, mode: str) -> dict:
    by_type: dict[str, list[RunResult]] = defaultdict(list)
    by_approach: dict[str, list[RunResult]] = defaultdict(list)
    by_approach_and_type: dict[tuple[str, str], list[RunResult]] = defaultdict(list)
    for result in results:
        type_name = result.instruction_type.value
        approach_name = result.approach.value
        by_type[type_name].append(result)
        by_approach[approach_name].append(result)
        by_approach_and_type[(approach_name, type_name)].append(result)

    failures = sorted(
        (
            item
            for item in results
            if item.error
            or item.score.intended_change_coverage < 1
            or item.score.collateral_damage_rate > 0
        ),
        key=lambda item: item.score.precision_loss,
        reverse=True,
    )
    return {
        "schema_version": 1,
        "mode": mode,
        "operation_cap": operation_cap,
        "actual_operations": sum(item.operations_used for item in results),
        "overall": _summary(results),
        "by_instruction_type": {key: _summary(value) for key, value in sorted(by_type.items())},
        "by_approach": {key: _summary(value) for key, value in sorted(by_approach.items())},
        "by_approach_and_instruction_type": {
            f"{approach}:{instruction_type}": _summary(value)
            for (approach, instruction_type), value in sorted(by_approach_and_type.items())
        },
        "failures": [item.model_dump(mode="json") for item in failures],
        "results": [item.model_dump(mode="json") for item in results],
    }
