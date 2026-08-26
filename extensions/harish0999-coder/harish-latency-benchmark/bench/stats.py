"""
Statistics over a batch of PhaseResult objects.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Iterable


@dataclasses.dataclass
class PhaseStats:
    phase: str
    n_total: int
    n_rate_limited: int
    n_errored: int
    n_ok: int
    median_s: float
    p95_s: float
    p99_s: float
    min_s: float
    max_s: float
    rate_limit_fraction: float


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (pct / 100.0) * (len(sorted_vals) - 1)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return d0 + d1


def compute_phase_stats(phase: str, results: Iterable) -> PhaseStats:
    results = list(results)
    n_total = len(results)
    rate_limited = [r for r in results if r.rate_limited]
    errored = [r for r in results if not r.rate_limited and (r.error or r.status_code >= 400)]
    ok = [r for r in results if not r.rate_limited and not r.error and r.status_code < 400]

    latencies = sorted(r.latency_s for r in ok)
    return PhaseStats(
        phase=phase,
        n_total=n_total,
        n_rate_limited=len(rate_limited),
        n_errored=len(errored),
        n_ok=len(ok),
        median_s=_percentile(latencies, 50),
        p95_s=_percentile(latencies, 95),
        p99_s=_percentile(latencies, 99),
        min_s=(latencies[0] if latencies else float("nan")),
        max_s=(latencies[-1] if latencies else float("nan")),
        rate_limit_fraction=(len(rate_limited) / n_total if n_total else 0.0),
    )


def load_generator_overhead_check(dispatch_latencies_s: list[float], concurrency: int,
                                   warn_threshold_s: float = 0.05) -> dict:
    if not dispatch_latencies_s:
        return {"checked": False, "reason": "no samples"}
    mean_dispatch = sum(dispatch_latencies_s) / len(dispatch_latencies_s)
    max_dispatch = max(dispatch_latencies_s)
    is_bottleneck = mean_dispatch > warn_threshold_s
    return {
        "checked": True,
        "concurrency": concurrency,
        "mean_dispatch_s": mean_dispatch,
        "max_dispatch_s": max_dispatch,
        "warn_threshold_s": warn_threshold_s,
        "generator_is_bottleneck": is_bottleneck,
    }
