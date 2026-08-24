"""End-to-end pipeline orchestration.

    source text ─▶ parse ─▶ snapshot/hash ──────────────────────┐
    target text ─▶ parse ─▶ align sections                      │ verified at every
                       │                                        │ checkpoint below
                       ▼                                        │
         for each section pair:                                 │
           provider.analyze()  → back-translation + semantic     │
           deterministic signals(source, back-translation)       │
           drift_engine.analyze_section_pair() → findings        │
           cache findings under (section content hash)           │
                       │                                        │
                       ▼                                        │
                 bilingual report  ◀── integrity re-verified ────┘

Resumability: findings are cached in a per-run JSON file keyed by each
section pair's content hash. Re-running with the same ``run_id`` skips any
section whose source+target content hash matches what's cached and reuses
its findings verbatim (verified by ``test_pipeline_idempotency.py``,
including a simulated mid-run provider failure that a second run then
completes). Findings are addressed by a hash-derived, not random, ID
(drift_engine.stable_finding_id), so a *fresh* run over unchanged input also
reproduces the same finding set — true idempotency, not just caching.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from drift_check.alignment import align_sections
from drift_check.audit import AuditLog
from drift_check.drift_engine import alignment_uncertain_finding, analyze_section_pair
from drift_check.integrity import SourceGuard, sha256_hex
from drift_check.models import Document, DriftFinding, RunMetrics, VerificationResult, utc_now_iso
from drift_check.parsing import parse_document
from drift_check.providers.base import ProviderError, TranslationAnalysisProvider
from drift_check.serialize import finding_from_dict, finding_to_dict
from drift_check.signals import run_all_detectors


class RunStateStore:
    """Per-run JSON cache of processed section pairs, keyed by content hash."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, object]] = self._load()

    def _load(self) -> dict[str, dict[str, object]]:
        if self._path.exists():
            loaded: dict[str, dict[str, object]] = json.loads(self._path.read_text(encoding="utf-8"))
            return loaded
        return {}

    def get_cached(self, section_index: int, pair_hash: str) -> list[dict[str, object]] | None:
        entry = self._data.get(str(section_index))
        if entry and entry.get("pair_hash") == pair_hash:
            findings = entry.get("findings")
            assert isinstance(findings, list)
            return findings
        return None

    def save(self, section_index: int, pair_hash: str, findings: list[dict[str, object]]) -> None:
        self._data[str(section_index)] = {"pair_hash": pair_hash, "findings": findings}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data), encoding="utf-8")


@dataclass
class RunResult:
    run_id: str
    source_document: Document
    target_document: Document
    findings: list[DriftFinding]
    metrics: RunMetrics
    audit: AuditLog
    integrity_verifications: list[VerificationResult]
    source_guard: SourceGuard


def run_pipeline(
    *,
    run_id: str,
    source_raw_text: str,
    target_raw_text: str,
    source_document_id: str,
    target_document_id: str,
    source_lang: str,
    target_lang: str,
    provider: TranslationAnalysisProvider,
    protected_terms: tuple[str, ...] = (),
    state_dir: Path | None = None,
    audit_path: Path | None = None,
) -> RunResult:
    metrics = RunMetrics(run_id=run_id, started_at=utc_now_iso())
    audit = AuditLog(run_id, audit_path)
    audit.record(
        "run_started",
        source_document_id=source_document_id,
        target_document_id=target_document_id,
        source_lang=source_lang,
        target_lang=target_lang,
        provider=provider.name,
    )

    # The immutable source: parsed once, hashed once, never touched again.
    source_doc = parse_document(source_raw_text, document_id=source_document_id, language=source_lang)
    source_doc = replace(source_doc, protected_terms=protected_terms)
    guard = SourceGuard.from_raw_text(source_document_id, source_raw_text, source_doc.sections)
    audit.record(
        "source_snapshot_taken",
        source_hash=guard.snapshot.whole_document_hash,
        section_count=guard.snapshot.section_count,
    )

    target_doc = parse_document(target_raw_text, document_id=target_document_id, language=target_lang)

    integrity_verifications: list[VerificationResult] = []

    def checkpoint(label: str) -> None:
        result = guard.assert_intact(source_raw_text, source_doc.sections)
        integrity_verifications.append(result)
        metrics.integrity_checks_ok += 1
        audit.record("integrity_verified", checkpoint=label, ok=result.ok)

    checkpoint("after_parsing")

    pairs = align_sections(source_doc, target_doc)
    metrics.sections_total = len(pairs)
    audit.record("sections_aligned", pair_count=len(pairs))

    source_by_id = {s.id: s for s in source_doc.sections}
    target_by_id = {s.id: s for s in target_doc.sections}

    state_store = RunStateStore(state_dir / f"{run_id}.json") if state_dir else None

    findings: list[DriftFinding] = []

    for pair in pairs:
        source_section = source_by_id.get(pair.source_section_id)
        target_section = target_by_id.get(pair.target_section_id)

        if source_section is None or target_section is None:
            findings.append(
                alignment_uncertain_finding(
                    run_id=run_id,
                    source_document_id=source_doc.id,
                    source_section=source_section,
                    target_section=target_section,
                    reason=pair.reason or "unmatched section",
                )
            )
            audit.record("section_alignment_uncertain", reason=pair.reason)
            continue

        pair_hash = sha256_hex(f"{source_section.content_hash}:{target_section.content_hash}")

        cached = state_store.get_cached(source_section.index, pair_hash) if state_store else None
        if cached is not None:
            findings.extend(finding_from_dict(d) for d in cached)
            metrics.sections_skipped_cached += 1
            audit.record("section_skipped_cached", section_index=source_section.index)
            checkpoint(f"after_section_{source_section.index}_cache_hit")
            continue

        try:
            bt = provider.analyze(
                target_text=target_section.text,
                source_text=source_section.text,
                target_section_id=target_section.id,
                section_index=target_section.index,
                source_lang=source_lang,
                target_lang=target_lang,
            )
        except ProviderError as exc:
            audit.record("section_provider_failed", section_index=source_section.index, error=str(exc))
            findings.append(
                alignment_uncertain_finding(
                    run_id=run_id,
                    source_document_id=source_doc.id,
                    source_section=source_section,
                    target_section=target_section,
                    reason=f"provider failed after retries: {exc}",
                )
            )
            checkpoint(f"after_section_{source_section.index}_provider_failure")
            continue

        metrics.provider_calls += 1
        metrics.provider_retries += bt.retries
        metrics.total_latency_ms += bt.latency_ms

        deterministic_signals = run_all_detectors(
            source_section.text,
            bt.text,
            language=source_lang,
            protected_terms=protected_terms,
        )

        section_findings = analyze_section_pair(
            run_id=run_id,
            source_document_id=source_doc.id,
            source_section=source_section,
            target_section=target_section,
            bt=bt,
            deterministic_signals=deterministic_signals,
            alignment_review_required=pair.review_required,
        )
        findings.extend(section_findings)
        metrics.sections_processed += 1

        if state_store:
            state_store.save(source_section.index, pair_hash, [finding_to_dict(f) for f in section_findings])

        audit.record(
            "section_processed",
            section_index=source_section.index,
            provider=bt.provider,
            model=bt.model,
            latency_ms=bt.latency_ms,
            retries=bt.retries,
            finding_count=len(section_findings),
        )
        checkpoint(f"after_section_{source_section.index}")

    checkpoint("final")
    metrics.findings_total = len(findings)
    metrics.stop_timer()
    audit.record("run_completed", findings_total=len(findings), sections_processed=metrics.sections_processed)

    return RunResult(
        run_id=run_id,
        source_document=source_doc,
        target_document=target_doc,
        findings=findings,
        metrics=metrics,
        audit=audit,
        integrity_verifications=integrity_verifications,
        source_guard=guard,
    )
