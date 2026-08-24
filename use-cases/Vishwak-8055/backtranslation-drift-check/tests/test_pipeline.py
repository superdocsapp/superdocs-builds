from __future__ import annotations

from pathlib import Path

from conftest import FIXTURES_DIR
from demo_providers import build_flagship_provider, build_second_doc_provider

from drift_check.alignment import align_sections
from drift_check.parsing import parse_document
from drift_check.pipeline import run_pipeline
from drift_check.providers.fixture import FixtureProvider


def _read(rel: str) -> str:
    return (FIXTURES_DIR / rel).read_text(encoding="utf-8")


class TestFlagshipDemo:
    def test_all_ten_seeded_cases_plus_bonus_sections(self) -> None:
        result = run_pipeline(
            run_id="test-flagship",
            source_raw_text=_read("flagship/source_en.md"),
            target_raw_text=_read("flagship/target_es.md"),
            source_document_id="medsure",
            target_document_id="medsure-es",
            source_lang="en",
            target_lang="es",
            provider=build_flagship_provider(),
            protected_terms=("MedSure Compliance Board (MCB)",),
        )
        assert result.metrics.sections_total == 12
        by_section: dict[int, list[str]] = {}
        for f in result.findings:
            by_section.setdefault(f.section_index, []).append(f.severity.value)

        # True negatives: sections 1-2 must PASS (INFO only, no drift finding).
        assert by_section[1] == ["info"]
        assert by_section[2] == ["info"]

        # True positives: sections 3-12 must all contain a real finding.
        for idx in range(3, 13):
            assert "info" not in by_section[idx], f"section {idx} unexpectedly passed"

        assert "critical" in by_section[3]  # must not -> may
        assert "high" in by_section[4]  # must -> should
        assert "high" in by_section[5]  # 30 -> 60
        assert "high" in by_section[6]  # 5% -> 15%
        assert "high" in by_section[7]  # at least removed
        assert "critical" in by_section[8]  # date changed
        assert "critical" in by_section[9]  # unit changed
        assert by_section[10]  # entity altered
        assert "critical" in by_section[11]  # dual-signal: modal + semantic corroboration
        assert "critical" in by_section[12]  # semantic-only: capillary -> venous

        semantic_only = [f for f in result.findings if f.section_index == 12]
        assert all(not f.verified_deterministically for f in semantic_only if not f.is_pass)

        dual_signal = [
            f for f in result.findings if f.section_index == 11 and f.category.value == "modal_obligation_change"
        ]
        assert dual_signal and dual_signal[0].semantic_corroborated

        assert all(v.ok for v in result.integrity_verifications)
        assert len(result.integrity_verifications) >= result.metrics.sections_total

        for f in result.findings:
            if f.proposed_correction:
                assert f.proposed_correction.correction_target == "translation"


class TestSecondDocumentGeneralization:
    def test_different_domain_and_language_pair_still_works(self) -> None:
        result = run_pipeline(
            run_id="test-second-doc",
            source_raw_text=_read("second_doc/source_en.md"),
            target_raw_text=_read("second_doc/target_fr.md"),
            source_document_id="acme-policy",
            target_document_id="acme-policy-fr",
            source_lang="en",
            target_lang="fr",
            provider=build_second_doc_provider(),
        )
        assert result.metrics.sections_total == 4
        by_section = {f.section_index: f for f in result.findings}
        assert by_section[1].severity.value == "info"
        assert by_section[2].category.value == "numeric_change"
        assert by_section[3].category.value == "modal_obligation_change"
        assert by_section[4].severity.value == "info"
        assert all(v.ok for v in result.integrity_verifications)


class TestIdempotencyAndResumability:
    def test_fresh_rerun_produces_identical_finding_ids(self) -> None:
        kwargs = dict(
            run_id="idempotency-check",
            source_raw_text=_read("second_doc/source_en.md"),
            target_raw_text=_read("second_doc/target_fr.md"),
            source_document_id="acme-policy",
            target_document_id="acme-policy-fr",
            source_lang="en",
            target_lang="fr",
        )
        r1 = run_pipeline(provider=build_second_doc_provider(), **kwargs)  # type: ignore[arg-type]
        r2 = run_pipeline(provider=build_second_doc_provider(), **kwargs)  # type: ignore[arg-type]
        assert {f.id for f in r1.findings} == {f.id for f in r2.findings}
        assert len(r1.findings) == len(r2.findings)

    def test_resume_after_mid_run_provider_failure(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state"
        source = _read("second_doc/source_en.md")
        target = _read("second_doc/target_fr.md")
        common = dict(
            run_id="resume-check",
            source_raw_text=source,
            target_raw_text=target,
            source_document_id="acme-policy",
            target_document_id="acme-policy-fr",
            source_lang="en",
            target_lang="fr",
            state_dir=state_dir,
        )

        # First attempt: section 3 fails every time it's tried (budget=99 >> attempts).
        flaky = FixtureProvider(
            {1: "x", 2: "y", 3: "z", 4: "w"},
            fail_first_n_calls_for_index={3: 99},
        )
        # Patch in real back-translations for sections that should succeed.
        flaky._back_translations = {  # type: ignore[attr-defined]
            1: (
                "This policy explains how employees can request reimbursement for home office equipment. "
                "It applies to all full-time remote employees."
            ),
            2: "Employees may be reimbursed for up to $800 per calendar year for approved home-office equipment.",
            3: "Receipts should be submitted within 14 days of purchase to qualify for reimbursement.",
            4: "The finance team will review and approve eligible requests within five business days.",
        }
        r1 = run_pipeline(provider=flaky, **common)  # type: ignore[arg-type]
        assert r1.metrics.sections_processed == 3  # sections 1, 2, 4 succeeded
        section3_findings = [f for f in r1.findings if f.section_index == 3]
        assert len(section3_findings) == 1
        assert section3_findings[0].category.value == "alignment_uncertain"

        # Second attempt with a healthy provider: sections 1/2/4 are cache
        # hits (no provider call), section 3 gets processed for real.
        healthy = build_second_doc_provider()
        r2 = run_pipeline(provider=healthy, **common)  # type: ignore[arg-type]
        assert r2.metrics.sections_skipped_cached == 3
        assert r2.metrics.sections_processed == 1
        assert healthy.call_log == [3]
        section3_findings_2 = [f for f in r2.findings if f.section_index == 3]
        assert any(f.category.value == "modal_obligation_change" for f in section3_findings_2)


class TestAlignmentEdgeCases:
    def test_empty_translation_is_review_required_not_a_crash(self) -> None:
        source = parse_document("# T\n\n## One\nHello.\n", document_id="s", language="en")
        target = parse_document("", document_id="t", language="es")
        pairs = align_sections(source, target)
        assert len(pairs) == 1
        assert pairs[0].review_required is True

    def test_section_count_mismatch_flags_review_required(self) -> None:
        source = parse_document("# T\n\n## One\nA.\n\n## Two\nB.\n", document_id="s", language="en")
        target = parse_document("# T\n\n## Uno\nA.\n", document_id="t", language="es")
        pairs = align_sections(source, target)
        assert all(p.review_required for p in pairs)

    def test_duplicate_headings_get_unique_ids(self) -> None:
        doc = parse_document(
            "# T\n\n## Notes\nFirst.\n\n## Notes\nSecond.\n", document_id="s", language="en"
        )
        ids = [s.id for s in doc.sections]
        assert len(ids) == len(set(ids))

    def test_unicode_and_empty_document_do_not_crash(self) -> None:
        doc = parse_document("héllo wörld 🎉 \u0301", document_id="s", language="en")
        assert doc.sections == ()
        assert doc.source_hash

    def test_pipeline_handles_zero_section_source_gracefully(self) -> None:
        result = run_pipeline(
            run_id="empty-doc",
            source_raw_text="no headings here at all",
            target_raw_text="tampoco aqui",
            source_document_id="empty",
            target_document_id="empty-t",
            source_lang="en",
            target_lang="es",
            provider=FixtureProvider({}),
        )
        assert result.findings == []
        assert all(v.ok for v in result.integrity_verifications)
