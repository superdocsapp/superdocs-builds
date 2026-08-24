from __future__ import annotations

import pytest

from drift_check.integrity import SourceGuard, SourceIntegrityError, sha256_hex
from drift_check.parsing import parse_document

SOURCE = """# Title

## Section One
The user must comply.

## Section Two
The fee is 5%.
"""


def test_hash_is_deterministic() -> None:
    assert sha256_hex(SOURCE) == sha256_hex(SOURCE)
    assert sha256_hex(SOURCE) != sha256_hex(SOURCE + " ")


def test_verify_passes_on_unchanged_source() -> None:
    doc = parse_document(SOURCE, document_id="d1", language="en")
    guard = SourceGuard.from_raw_text("d1", SOURCE, doc.sections)
    result = guard.assert_intact(SOURCE, doc.sections)
    assert result.ok


def test_deliberate_mutation_is_detected() -> None:
    """Section 9 of the spec: attempt to alter the source and confirm the guard catches it."""
    doc = parse_document(SOURCE, document_id="d1", language="en")
    guard = SourceGuard.from_raw_text("d1", SOURCE, doc.sections)

    mutated = SOURCE.replace("must comply", "may comply")
    with pytest.raises(SourceIntegrityError):
        guard.assert_intact(mutated, doc.sections)


def test_section_level_mutation_is_detected_even_if_whole_doc_hash_ok() -> None:
    doc = parse_document(SOURCE, document_id="d1", language="en")
    guard = SourceGuard.from_raw_text("d1", SOURCE, doc.sections)

    mutated_sections = list(doc.sections)
    mutated_sections[0] = mutated_sections[0].__class__(
        id=mutated_sections[0].id,
        index=mutated_sections[0].index,
        heading=mutated_sections[0].heading,
        text="tampered",
        content_hash="0" * 64,
    )
    result = guard.verify_sections(tuple(mutated_sections))
    assert not result.ok


def test_pipeline_never_writes_to_the_source_file(tmp_path: object) -> None:
    from pathlib import Path

    from drift_check.pipeline import run_pipeline
    from drift_check.providers.fixture import FixtureProvider

    tmp = Path(str(tmp_path))
    source_path = tmp / "source.md"
    source_path.write_text(SOURCE, encoding="utf-8")
    before = source_path.read_bytes()
    before_mtime = source_path.stat().st_mtime_ns

    provider = FixtureProvider({1: "The user must comply.", 2: "The fee is 5%."})
    result = run_pipeline(
        run_id="immutability-check",
        source_raw_text=source_path.read_text(encoding="utf-8"),
        target_raw_text=SOURCE,
        source_document_id="d1",
        target_document_id="d1-t",
        source_lang="en",
        target_lang="en",
        provider=provider,
    )
    assert all(v.ok for v in result.integrity_verifications)
    assert source_path.read_bytes() == before
    assert source_path.stat().st_mtime_ns == before_mtime
    assert all(
        f.proposed_correction is None or f.proposed_correction.correction_target == "translation"
        for f in result.findings
    )
