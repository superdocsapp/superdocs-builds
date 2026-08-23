"""Closes the calibration loop with real outcomes, not just a one-shot
dual-extraction signal.

app/workflow/calibration.py answers "do two independent extraction runs
agree" -- a per-run signal, available immediately, no history needed.
This module answers a different, complementary question: "of every
field we scored around 0.75, what fraction did a human actually
approve unchanged?" That's a real calibration curve, and it can only be
built from accumulated review-decision history -- it has nothing
useful to say on a tenant's first day, and becomes more trustworthy the
more decisions accumulate.

If the two disagree (self-reported+dual-extraction 0.75 corresponds to
only a 40% real approval rate), THAT is the strongest possible evidence
the pipeline's confidence numbers are miscalibrated for this tenant's
document mix -- and the fix is inspectable per field, not a single
global "trust the model more/less" knob.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Confidence buckets. Matches common calibration-curve bucketing
# (deciles would also be reasonable; quintiles keep bucket populations
# large enough to be statistically meaningful sooner for a tenant with
# moderate volume, which matters more here than bucket precision).
_BUCKET_EDGES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.01]  # 1.01 so confidence==1.0 falls in the last bucket
_BUCKET_LABELS = ["0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]


def _bucket_for(confidence: float) -> str:
    for i in range(len(_BUCKET_EDGES) - 1):
        if _BUCKET_EDGES[i] <= confidence < _BUCKET_EDGES[i + 1]:
            return _BUCKET_LABELS[i]
    return _BUCKET_LABELS[-1]


@dataclass
class BucketStats:
    bucket: str
    approved: int = 0
    rejected: int = 0

    @property
    def total(self) -> int:
        return self.approved + self.rejected

    @property
    def approval_rate(self) -> Optional[float]:
        return (self.approved / self.total) if self.total else None

    @property
    def calibration_gap(self) -> Optional[float]:
        """approval_rate minus the bucket's own midpoint confidence --
        near 0 means well-calibrated (a 0.6-0.8 bucket really does get
        approved ~70% of the time); a large negative value means the
        pipeline is systematically OVER-confident for this bucket
        (scores look higher than the real approval rate warrants) and
        the tenant's threshold may need to be raised."""
        if self.total == 0:
            return None
        edges = dict(zip(_BUCKET_LABELS, zip(_BUCKET_EDGES, _BUCKET_EDGES[1:])))
        lo, hi = edges[self.bucket]
        midpoint = (lo + min(hi, 1.0)) / 2
        return self.approval_rate - midpoint


class CalibrationTracker:
    """Per-tenant (one instance per TenantContext, same pattern as every
    other per-tenant store in this codebase). record_outcome() should be
    called from apply_review_decision() every time a human approves or
    rejects a held-back field -- this is observational, not a gate, so
    it never blocks or changes pipeline behavior; it only accumulates
    evidence for later reporting via bucket_report()."""

    def __init__(self) -> None:
        # keyed by (field_name, bucket) so a tenant can see "contract_value
        # at 0.6-0.8" separately from "counterparty_name at 0.6-0.8" --
        # different fields can be miscalibrated in different directions.
        self._stats: dict[tuple[str, str], BucketStats] = {}

    def record_outcome(self, field_name: str, original_confidence: float, approved: bool) -> None:
        bucket = _bucket_for(original_confidence)
        key = (field_name, bucket)
        stats = self._stats.setdefault(key, BucketStats(bucket=bucket))
        if approved:
            stats.approved += 1
        else:
            stats.rejected += 1

    def bucket_report(self, field_name: Optional[str] = None) -> list[dict]:
        """Returns one row per (field, bucket) with at least one
        decision, sorted for stable, readable output. Filterable by
        field_name so a tenant can drill into e.g. just contract_value."""
        rows = []
        for (fname, bucket), stats in self._stats.items():
            if field_name is not None and fname != field_name:
                continue
            rows.append(
                {
                    "field_name": fname,
                    "confidence_bucket": bucket,
                    "approved": stats.approved,
                    "rejected": stats.rejected,
                    "total": stats.total,
                    "approval_rate": stats.approval_rate,
                    "calibration_gap": stats.calibration_gap,
                }
            )
        rows.sort(key=lambda r: (r["field_name"], r["confidence_bucket"]))
        return rows

    def worst_calibrated_fields(self, min_samples: int = 5, top_n: int = 5) -> list[dict]:
        """Buckets with enough samples to be meaningful (min_samples),
        ranked by |calibration_gap| descending -- the fields/buckets
        most worth a tenant's attention first. Buckets below
        min_samples are excluded rather than reported with a misleading
        gap computed from too little data."""
        rows = [r for r in self.bucket_report() if r["total"] >= min_samples and r["calibration_gap"] is not None]
        rows.sort(key=lambda r: abs(r["calibration_gap"]), reverse=True)
        return rows[:top_n]

    def suggest_thresholds(
        self, target_approval_rate: float = 0.9, min_samples: int = 10
    ) -> dict[str, dict]:
        """Suggests a corrected field_threshold per field based on
        accumulated real outcomes -- never applies it. A tenant's
        review_threshold is a policy decision about acceptable risk
        (how often are we OK with a human catching a wrong value vs.
        how much review burden we're willing to carry); this function
        has no business making that trade-off for them. It only
        answers: "given the buckets we've actually seen, what's the
        LOWEST confidence bucket whose real approval rate meets or
        exceeds target_approval_rate" -- the evidence a tenant needs
        to make that call themselves.

        For each field with enough total samples across its buckets,
        walks buckets from highest confidence downward and returns the
        lower edge of the lowest bucket whose approval_rate still meets
        the target. If even the top bucket (0.8-1.0) falls short of
        target_approval_rate, suggests raising the threshold above what
        this pipeline currently produces at all (current_max_confidence
        signals that) rather than silently suggesting something
        untested.

        Fields with fewer than min_samples total decisions are omitted
        -- not enough evidence to suggest anything responsibly."""
        # bucket lower edges, matched to _BUCKET_LABELS order (already
        # highest-to-lowest is what we want to walk, so reverse it)
        edges_by_label = dict(zip(_BUCKET_LABELS, _BUCKET_EDGES))
        by_field: dict[str, dict[str, BucketStats]] = {}
        for (fname, bucket), stats in self._stats.items():
            by_field.setdefault(fname, {})[bucket] = stats

        suggestions: dict[str, dict] = {}
        for fname, buckets in by_field.items():
            total_samples = sum(s.total for s in buckets.values())
            if total_samples < min_samples:
                continue
            chosen_edge = None
            for label in reversed(_BUCKET_LABELS):  # highest bucket first
                stats = buckets.get(label)
                if stats is None or stats.total == 0:
                    continue
                if stats.approval_rate is not None and stats.approval_rate >= target_approval_rate:
                    chosen_edge = edges_by_label[label]
                else:
                    break  # first bucket (from the top) that misses target -- stop walking down
            suggestions[fname] = {
                "suggested_threshold": chosen_edge,
                "total_samples": total_samples,
                "target_approval_rate": target_approval_rate,
                "note": (
                    f"no confidence bucket met the {target_approval_rate:.0%} target -- "
                    f"consider this field unreliable at any threshold this pipeline currently "
                    f"produces, not just under-thresholded"
                    if chosen_edge is None
                    else f"lowest confidence bucket meeting target starts at {chosen_edge}"
                ),
            }
        return suggestions
