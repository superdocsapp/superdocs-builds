"""
Turns runner.run_benchmark()'s raw CycleResult data into per-phase
PhaseStats and a derived sizing guide.
"""
from __future__ import annotations

from .stats import compute_phase_stats, load_generator_overhead_check


def phase_results_for(all_results: dict, tier: str, conc: int, phase: str) -> list:
    cycles = all_results.get((tier, conc), [])
    out = []
    for c in cycles:
        for p in c.phases:
            if p.phase == phase:
                out.append(p)
    return out


PHASES = ["upload", "processing", "editing", "export"]


def build_report(all_results: dict) -> dict:
    cells = sorted(set(all_results.keys()))
    stats_by_cell = {}
    for tier, conc in cells:
        stats_by_cell[(tier, conc)] = {
            phase: compute_phase_stats(phase, phase_results_for(all_results, tier, conc, phase))
            for phase in PHASES
        }

    dispatch_by_cell = {}
    fatal_by_cell = {}
    for (tier, conc), cycles in all_results.items():
        dispatch_latencies = [c.dispatch_latency_s for c in cycles if not c.fatal_error]
        dispatch_by_cell[(tier, conc)] = load_generator_overhead_check(dispatch_latencies, conc)
        fatal_by_cell[(tier, conc)] = [c.fatal_error for c in cycles if c.fatal_error]

    return {
        "cells": cells,
        "stats_by_cell": stats_by_cell,
        "dispatch_by_cell": dispatch_by_cell,
        "fatal_by_cell": fatal_by_cell,
        "sizing_guide": render_sizing_guide(cells, stats_by_cell, fatal_by_cell),
    }


def render_sizing_guide(cells, stats_by_cell, fatal_by_cell=None) -> str:
    if not cells:
        return "No data collected -- run the benchmark first."
    fatal_by_cell = fatal_by_cell or {}

    lines = ["# SuperDocs Integration Sizing Guide", "",
              "Derived directly from the latency/throughput results in this run. "
              "Numbers below are p50/p95 wall-clock seconds per phase, not "
              "averages -- plan for the tail, not the median.", ""]

    for tier, conc in cells:
        phase_stats = stats_by_cell[(tier, conc)]
        total_p50 = sum(s.median_s for s in phase_stats.values() if s.n_ok)
        total_p95 = sum(s.p95_s for s in phase_stats.values() if s.n_ok)
        lines.append(f"## {tier} document, concurrency={conc}")
        fatals = fatal_by_cell.get((tier, conc), [])
        if fatals:
            lines.append(f"- **{len(fatals)} cycle(s) failed with an unhandled/fatal error** "
                          f"(see bench_report.json for details) -- excluded from stats below")
        for phase in PHASES:
            s = phase_stats[phase]
            if s.n_ok == 0:
                lines.append(f"- **{phase}**: no successful samples "
                              f"({s.n_rate_limited} rate-limited, {s.n_errored} errored)")
                continue
            lines.append(
                f"- **{phase}**: p50={s.median_s:.2f}s, p95={s.p95_s:.2f}s, "
                f"p99={s.p99_s:.2f}s (n={s.n_ok} ok, {s.n_rate_limited} rate-limited "
                f"[{s.rate_limit_fraction:.0%}], {s.n_errored} errored)"
            )
        lines.append(f"- **End-to-end (sum of phase p50/p95)**: ~{total_p50:.2f}s typical, "
                      f"~{total_p95:.2f}s worst-observed-case")
        lines.append("")

    lines.append("## Reading this")
    lines.append(
        "- If your integration is interactive (a human waiting on a review UI), "
        "budget for the p95 end-to-end number, not p50 -- roughly 1 in 20 "
        "requests will be at or beyond it."
    )
    lines.append(
        "- If a cell shows a non-trivial rate-limited fraction, that concurrency "
        "level exceeds what the current plan tier sustains; either lower "
        "concurrency or budget for backoff/retry time in addition to the "
        "latencies above."
    )
    return "\n".join(lines)
