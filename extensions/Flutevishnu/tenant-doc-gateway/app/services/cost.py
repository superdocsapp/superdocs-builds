"""Estimate SuperDocs operation cost per request.

Provides cost-per-request tracking for budget discipline against upstream API limits.
Since exact billing is authoritative upstream, the service logs both local estimates 
and any usage figure returned by the provider.

Cost tracking rules:
- Edits cost operations (one edit operation covers up to 25 sections).
- Exports and downloads do not consume operations.
"""

from __future__ import annotations

from app.db.models import JobType

# Rough per-job-type estimate in "operations". Kept as data so tuning is a
# config/data change, not new code.
_ESTIMATE: dict[JobType, float] = {
    JobType.UPLOAD: 0.0,   # upload/parse itself is not a billed edit op
    JobType.EDIT: 1.0,     # one edit operation (<= 25 sections)
    JobType.EXPORT: 0.0,   # exports are free
}


def estimate_ops(job_type: JobType) -> float:
    return _ESTIMATE.get(job_type, 1.0)


def reconcile(estimate: float, upstream_reported: float | None) -> float:
    """Prefer the upstream number when present; fall back to our estimate."""
    if upstream_reported is not None and upstream_reported > 0:
        return upstream_reported
    return estimate
