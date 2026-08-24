"""Round-trip serialization for DriftFinding.

Used in two places that both need it for different reasons: the run-state
cache (pipeline.py) writes findings to disk so a resumed run can skip
already-processed sections, and the JSON report (report.py) exports findings
for machine consumption. Keeping one conversion here means both stay in
sync with the model automatically.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from drift_check.models import (
    DriftCategory,
    DriftFinding,
    Evidence,
    ProposedCorrection,
    ReviewStatus,
    Severity,
)


def finding_to_dict(finding: DriftFinding) -> dict[str, Any]:
    d = asdict(finding)
    d["category"] = finding.category.value
    d["severity"] = finding.severity.value
    d["review_status"] = finding.review_status.value
    return d


def finding_from_dict(d: dict[str, Any]) -> DriftFinding:
    evidence = [Evidence(**e) for e in d["evidence"]]
    correction = ProposedCorrection(**d["proposed_correction"]) if d.get("proposed_correction") else None
    return DriftFinding(
        id=d["id"],
        run_id=d["run_id"],
        source_document_id=d["source_document_id"],
        source_section_id=d["source_section_id"],
        target_section_id=d["target_section_id"],
        section_index=d["section_index"],
        category=DriftCategory(d["category"]),
        severity=Severity(d["severity"]),
        source_text=d["source_text"],
        target_text=d["target_text"],
        back_translation=d["back_translation"],
        difference=d["difference"],
        evidence=evidence,
        confidence=d["confidence"],
        proposed_correction=correction,
        review_status=ReviewStatus(d["review_status"]),
        verified_deterministically=d["verified_deterministically"],
        semantic_corroborated=d.get("semantic_corroborated", False),
        created_at=d["created_at"],
    )
