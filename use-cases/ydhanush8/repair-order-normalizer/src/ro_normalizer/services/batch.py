"""Batch processing over a day's worth of repair orders.

Two things the brief is explicit about, both enforced here rather than left to
discipline:

* **Small-sample mode is the default.** `max_orders` caps every run. Nothing
  processes a hundred orders because someone forgot a flag.
* **A stopping rule.** `max_failures` aborts a batch that is going wrong instead
  of grinding through ninety-eight more of the same error.

The summary counts what a service manager acts on: how many orders need a human
before they can be claimed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ro_normalizer.normalizer import normalize
from ro_normalizer.schemas import BatchSummary, Confidence, NormalizedOrder, RepairOrder


class BatchAborted(RuntimeError):
    """The stopping rule fired."""


@dataclass
class BatchResult:
    results: list[NormalizedOrder] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    aborted: bool = False

    @property
    def summary(self) -> BatchSummary:
        counts = {level: 0 for level in Confidence}
        warnings: dict[str, int] = {}

        for result in self.results:
            counts[result.confidence] += 1
            for warning in result.warnings:
                warnings[warning.code] = warnings.get(warning.code, 0) + 1

        return BatchSummary(
            total=len(self.results),
            high=counts[Confidence.HIGH],
            medium=counts[Confidence.MEDIUM],
            low=counts[Confidence.LOW],
            with_missing_elements=sum(1 for r in self.results if r.missing_elements),
            needs_review=sum(1 for r in self.results if r.needs_review),
            warnings=dict(sorted(warnings.items())),
        )


def load_orders(path: str | Path) -> list[RepairOrder]:
    payload = json.loads(Path(path).read_text())
    if isinstance(payload, dict):
        payload = payload.get("orders", [])
    return [RepairOrder(**item) for item in payload]


def run_batch(
    orders: Iterable[RepairOrder],
    *,
    max_orders: int = 5,
    max_failures: int = 3,
) -> BatchResult:
    """Normalize a batch, bounded on both ends.

    `max_orders` is the small-sample default; raise it deliberately.
    `max_failures` stops a batch that is failing systematically.
    """
    result = BatchResult()

    for index, order in enumerate(orders):
        if index >= max_orders:
            break
        try:
            result.results.append(normalize(order))
        except Exception as exc:  # noqa: BLE001 — recorded per order, batch continues
            result.failures.append((order.repair_order_id, f"{type(exc).__name__}: {exc}"))
            if len(result.failures) >= max_failures:
                result.aborted = True
                break

    return result


def iter_batches(orders: list[RepairOrder], size: int) -> Iterator[list[RepairOrder]]:
    for start in range(0, len(orders), size):
        yield orders[start : start + size]


def format_summary(summary: BatchSummary) -> str:
    lines = [
        f"Total orders      {summary.total}",
        f"  high confidence {summary.high}",
        f"  medium          {summary.medium}",
        f"  low             {summary.low}",
        f"Missing elements  {summary.with_missing_elements}",
        f"Needs review      {summary.needs_review}",
    ]
    if summary.warnings:
        lines.append("Warnings")
        for code, count in summary.warnings.items():
            lines.append(f"  {code:26s} {count}")
    return "\n".join(lines)
