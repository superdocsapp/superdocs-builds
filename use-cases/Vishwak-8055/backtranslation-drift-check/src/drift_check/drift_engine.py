"""Turns deterministic signals + a semantic assessment into DriftFinding records.

Aggregation rule: deterministic signals are grouped by ``DriftCategory``
*before* a finding is constructed, so two corroborating low-level signals
about the same underlying problem — e.g. both numbers in a "2°C to 8°C"
range having their unit swapped, or a protected-term miss and a
capitalized-phrase miss both pointing at the same altered entity — become
ONE user-facing ``DriftFinding`` with multiple ``Evidence`` entries, not two
separate findings that inflate the report's count. Severity is the max
across the group; every signal's own text is preserved verbatim in its own
``Evidence`` entry, so nothing is lost, only consolidated. See DECISIONS.md
#10.

Semantic corroboration rule: if the semantic assessment flags the same
``DriftCategory`` that the (now-aggregated) deterministic pass already
flagged for this section, it is treated as corroboration
(``semantic_corroborated=True`` on the existing finding), not a third
finding. If the semantic assessment flags drift in a category no
deterministic signal touched, it becomes its own finding with
``verified_deterministically=False``.

A section with neither deterministic signals nor semantic drift gets an
explicit PASS record (``STYLISTIC_VARIATION`` / ``Severity.INFO``) rather
than silence, so the report and audit trail account for every section that
was analyzed, not just the ones with problems.

Finding IDs are derived deterministically from ``(run_id, section, category,
sorted evidence signals)`` rather than random UUIDs, so identical reruns
produce identical IDs — this is what makes the pipeline's idempotency
guarantee possible (see pipeline.py).
"""

from __future__ import annotations

from drift_check.correction import (
    build_correction_for_semantic,
    build_correction_for_signal_group,
)
from drift_check.integrity import sha256_hex
from drift_check.models import (
    BackTranslationResult,
    DriftCategory,
    DriftFinding,
    Evidence,
    ReviewStatus,
    Section,
    Severity,
)
from drift_check.severity import initial_review_status
from drift_check.signals import Signal


def stable_finding_id(run_id: str, target_section_id: str, category: DriftCategory, evidence_signal: str) -> str:
    digest = sha256_hex(f"{run_id}\x1f{target_section_id}\x1f{category.value}\x1f{evidence_signal}")
    return f"F-{digest[:12]}"


def _group_signals_by_category(signals: list[Signal]) -> list[list[Signal]]:
    """Group signals by category, preserving first-seen order (stable, not sorted)."""
    groups: dict[DriftCategory, list[Signal]] = {}
    order: list[DriftCategory] = []
    for signal in signals:
        if signal.category not in groups:
            groups[signal.category] = []
            order.append(signal.category)
        groups[signal.category].append(signal)
    return [groups[category] for category in order]


def _summarize_signals(category: DriftCategory, signals: list[Signal]) -> str:
    if len(signals) == 1:
        return signals[0].difference
    label = category.value.replace("_", " ")
    return f"{len(signals)} corroborating {label} signals detected in this section (see evidence for each)."


def _finding_from_signal_group(
    *,
    run_id: str,
    source_document_id: str,
    source_section: Section,
    target_section: Section,
    back_translation_text: str,
    signals: list[Signal],
    alignment_review_required: bool,
) -> DriftFinding:
    category = signals[0].category
    severity = max((s.severity for s in signals), key=lambda sev: sev.rank)
    confidence = max(s.confidence for s in signals)
    combined_key = "|".join(sorted(s.evidence_signal for s in signals))

    review_status = initial_review_status(
        verified_deterministically=True,
        alignment_review_required=alignment_review_required,
        confidence=confidence,
    )
    return DriftFinding(
        id=stable_finding_id(run_id, target_section.id, category, combined_key),
        run_id=run_id,
        source_document_id=source_document_id,
        source_section_id=source_section.id,
        target_section_id=target_section.id,
        section_index=source_section.index,
        category=category,
        severity=severity,
        source_text=source_section.text,
        target_text=target_section.text,
        back_translation=back_translation_text,
        difference=_summarize_signals(category, signals),
        evidence=[
            Evidence(
                description=s.difference,
                source_excerpt=s.source_excerpt,
                target_excerpt=target_section.text[:160],
                back_translation_excerpt=s.back_translation_excerpt,
                signal=s.evidence_signal,
            )
            for s in signals
        ],
        confidence=confidence,
        proposed_correction=build_correction_for_signal_group(signals, target_section.text),
        review_status=review_status,
        verified_deterministically=True,
        semantic_corroborated=False,
    )


def _finding_from_semantic(
    *,
    run_id: str,
    source_document_id: str,
    source_section: Section,
    target_section: Section,
    bt: BackTranslationResult,
    alignment_review_required: bool,
) -> DriftFinding:
    assessment = bt.semantic_assessment
    assert assessment is not None and assessment.has_drift
    category = assessment.category or DriftCategory.SEMANTIC_DRIFT_OTHER
    severity = assessment.severity_hint or Severity.MEDIUM
    review_status = initial_review_status(
        verified_deterministically=False,
        alignment_review_required=alignment_review_required,
        confidence=assessment.confidence,
    )
    return DriftFinding(
        id=stable_finding_id(run_id, target_section.id, category, f"semantic:{category.value}"),
        run_id=run_id,
        source_document_id=source_document_id,
        source_section_id=source_section.id,
        target_section_id=target_section.id,
        section_index=source_section.index,
        category=category,
        severity=severity,
        source_text=source_section.text,
        target_text=target_section.text,
        back_translation=bt.text,
        difference=assessment.rationale,
        evidence=[
            Evidence(
                description=assessment.rationale,
                source_excerpt=source_section.text[:160],
                target_excerpt=target_section.text[:160],
                back_translation_excerpt=bt.text[:160],
                signal=f"semantic:{category.value}",
            )
        ],
        confidence=assessment.confidence,
        proposed_correction=build_correction_for_semantic(assessment),
        review_status=review_status,
        verified_deterministically=False,
        semantic_corroborated=False,
    )


def _pass_finding(
    *, run_id: str, source_document_id: str, source_section: Section, target_section: Section, bt: BackTranslationResult
) -> DriftFinding:
    return DriftFinding(
        id=stable_finding_id(run_id, target_section.id, DriftCategory.STYLISTIC_VARIATION, "pass"),
        run_id=run_id,
        source_document_id=source_document_id,
        source_section_id=source_section.id,
        target_section_id=target_section.id,
        section_index=source_section.index,
        category=DriftCategory.STYLISTIC_VARIATION,
        severity=Severity.INFO,
        source_text=source_section.text,
        target_text=target_section.text,
        back_translation=bt.text,
        difference="No meaning drift detected; differences (if any) are stylistic.",
        evidence=[],
        confidence=1.0,
        proposed_correction=None,
        review_status=ReviewStatus.APPROVED,
        verified_deterministically=True,
        semantic_corroborated=bt.semantic_assessment is not None and not bt.semantic_assessment.has_drift,
    )


def analyze_section_pair(
    *,
    run_id: str,
    source_document_id: str,
    source_section: Section,
    target_section: Section,
    bt: BackTranslationResult,
    deterministic_signals: list[Signal],
    alignment_review_required: bool,
) -> list[DriftFinding]:
    findings: list[DriftFinding] = [
        _finding_from_signal_group(
            run_id=run_id,
            source_document_id=source_document_id,
            source_section=source_section,
            target_section=target_section,
            back_translation_text=bt.text,
            signals=group,
            alignment_review_required=alignment_review_required,
        )
        for group in _group_signals_by_category(deterministic_signals)
    ]

    assessment = bt.semantic_assessment
    if assessment is not None and assessment.has_drift:
        assessed_category = assessment.category or DriftCategory.SEMANTIC_DRIFT_OTHER
        matching = next((f for f in findings if f.category == assessed_category), None)
        if matching is not None:
            matching.semantic_corroborated = True
            matching.severity = max(
                matching.severity, assessment.severity_hint or matching.severity, key=lambda sev: sev.rank
            )
        else:
            findings.append(
                _finding_from_semantic(
                    run_id=run_id,
                    source_document_id=source_document_id,
                    source_section=source_section,
                    target_section=target_section,
                    bt=bt,
                    alignment_review_required=alignment_review_required,
                )
            )

    if not findings:
        findings.append(
            _pass_finding(
                run_id=run_id,
                source_document_id=source_document_id,
                source_section=source_section,
                target_section=target_section,
                bt=bt,
            )
        )

    return findings


def alignment_uncertain_finding(
    *,
    run_id: str,
    source_document_id: str,
    source_section: Section | None,
    target_section: Section | None,
    reason: str,
) -> DriftFinding:
    """Build a finding for a pair the aligner could not confidently match at all."""
    target_id = target_section.id if target_section else ""
    section_index = source_section.index if source_section else (target_section.index if target_section else 0)
    return DriftFinding(
        id=stable_finding_id(run_id, target_id or "unmatched", DriftCategory.ALIGNMENT_UNCERTAIN, reason),
        run_id=run_id,
        source_document_id=source_document_id,
        source_section_id=source_section.id if source_section else "",
        target_section_id=target_id,
        section_index=section_index,
        category=DriftCategory.ALIGNMENT_UNCERTAIN,
        severity=Severity.HIGH,
        source_text=source_section.text if source_section else "",
        target_text=target_section.text if target_section else "",
        back_translation="",
        difference=reason,
        evidence=[],
        confidence=0.0,
        proposed_correction=None,
        review_status=ReviewStatus.REVIEW_REQUIRED,
        verified_deterministically=False,
        semantic_corroborated=False,
    )
