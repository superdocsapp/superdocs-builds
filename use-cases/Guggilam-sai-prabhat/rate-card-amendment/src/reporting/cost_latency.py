"""Phase 8: per-stage cost/latency summary, derived entirely from data the
graph already records (`stage_timings`, `audit_events`, `token_cost_estimates`
on `RunState` — see `src/agent/state.py`). No new state fields: operation
count, retry count, and cache-hit are all recoverable by counting existing
audit event types, so adding parallel counters onto every node would just be
duplicated bookkeeping.
"""

from __future__ import annotations

from typing import Any, TypedDict

MODEL_PROVIDER = "superdocs"  # the only external call site in this pipeline; see docs/COST_AND_LATENCY.md


class StageCostReport(TypedDict):
    stage: str
    started_at: str | None
    completed_at: str | None
    duration_ms: int | None
    model_provider: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    operation_count: int
    retry_count: int
    cache_hit_count: int


def summarize_stage_costs(run_state: dict[str, Any]) -> list[StageCostReport]:
    """One row per stage_timings entry, enriched with counts derived from
    audit_events and token_cost_estimates for that same stage."""

    events = run_state.get("audit_events", [])
    token_estimates = run_state.get("token_cost_estimates", [])

    reports = []
    for timing in run_state.get("stage_timings", []):
        stage = timing["stage"]
        stage_events = [e for e in events if e["stage"] == stage]
        stage_tokens = [t for t in token_estimates if t["stage"] == stage]

        reports.append(
            StageCostReport(
                stage=stage,
                started_at=timing.get("started_at"),
                completed_at=timing.get("completed_at"),
                duration_ms=timing.get("duration_ms"),
                model_provider=MODEL_PROVIDER,
                input_tokens=sum(t["input_tokens"] for t in stage_tokens),
                output_tokens=sum(t["output_tokens"] for t in stage_tokens),
                estimated_cost_usd=round(sum(t["estimated_cost_usd"] for t in stage_tokens), 6),
                operation_count=sum(1 for e in stage_events if e["event_type"] in ("stage_completed", "external_call")),
                retry_count=sum(1 for e in stage_events if e["event_type"] == "retry"),
                cache_hit_count=sum(
                    1 for e in stage_events if e["event_type"] == "stage_completed" and e["payload"].get("replayed_from_ledger")
                ),
            )
        )
    return reports
