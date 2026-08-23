"""Cost/latency accounting per calibration mode.

app/workflow/calibration.py and the ensemble extension in the same
module both say, in their docstrings, "this costs more SuperDocs
operations." That's true in the abstract but not actionable -- a
tenant deciding whether the accuracy trade-off is worth it needs to
know the REAL multiplier for THEIR document mix (some documents retry
more than others, so "2x" is a rough guide, not a guarantee), and
needs it in the same place they'd look to turn the setting on or off.

This module accumulates that per-run, keyed by which mode a given run
actually used (recorded via RunReport.calibration_mode, set by the
pipeline at the top of process()), and reports totals/averages per
mode plus the realized multiplier of each calibrated mode against the
"none" baseline.
"""
from __future__ import annotations

from dataclasses import dataclass

MODE_NONE = "none"
MODE_PAIRWISE = "pairwise"
MODE_ENSEMBLE = "ensemble"


@dataclass
class ModeStats:
    mode: str
    run_count: int = 0
    total_operations: int = 0
    total_latency_ms: float = 0.0

    @property
    def avg_operations_per_run(self) -> float:
        return (self.total_operations / self.run_count) if self.run_count else 0.0

    @property
    def avg_latency_ms_per_run(self) -> float:
        return (self.total_latency_ms / self.run_count) if self.run_count else 0.0


class CostTracker:
    """One instance per tenant (same pattern as CalibrationTracker),
    accumulated across every process() call regardless of outcome
    (success or partial) -- a run that failed a stage still spent real
    SuperDocs operations and its cost should count."""

    def __init__(self) -> None:
        self._stats: dict[str, ModeStats] = {}

    def record_run(self, mode: str, operations: int, latency_ms: float) -> None:
        stats = self._stats.setdefault(mode, ModeStats(mode=mode))
        stats.run_count += 1
        stats.total_operations += operations
        stats.total_latency_ms += latency_ms

    def report(self) -> dict:
        """Per-mode totals/averages, plus the realized operations
        multiplier of each calibrated mode versus the 'none' baseline
        -- e.g. "pairwise calibration actually cost this tenant 1.8x
        normal ops, not the roughly-2x the docstring suggests, because
        some documents' primary extraction already needed a retry."
        Multiplier is None when there's no 'none'-mode baseline yet to
        compare against, or the calibrated mode has no runs."""
        baseline = self._stats.get(MODE_NONE)
        rows = {}
        for mode, stats in self._stats.items():
            multiplier = None
            if mode != MODE_NONE and baseline and baseline.run_count and stats.run_count:
                if baseline.avg_operations_per_run > 0:
                    multiplier = stats.avg_operations_per_run / baseline.avg_operations_per_run
            rows[mode] = {
                "run_count": stats.run_count,
                "total_operations": stats.total_operations,
                "total_latency_ms": stats.total_latency_ms,
                "avg_operations_per_run": stats.avg_operations_per_run,
                "avg_latency_ms_per_run": stats.avg_latency_ms_per_run,
                "operations_multiplier_vs_none": multiplier,
            }
        return rows
