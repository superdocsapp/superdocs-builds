"""Golden-document regression suite.

Every other test in this repo checks that a *mechanism* works (retry
fires, review queue gates correctly, hash chain detects tampering).
None of them prove the pipeline's actual extraction OUTPUT is correct
and stays correct as the pipeline evolves -- that needs a fixed
document with a hand-verified expected answer, run end-to-end, diffed
field by field.

Each golden case below is a real (fabricated but realistic) source
document plus the exact fields, confidence bucket (not exact float --
see GoldenCase docstring), and retention_category a correct pipeline
run should produce. Running the whole suite after any change to
prompts, thresholds, extraction logic, or the accuracy layer is what
actually proves accuracy didn't regress -- a green test suite
elsewhere only proves the mechanisms still fire, not that they still
fire on CORRECT values.

Uses the fake SuperDocs client (deterministic, offline) rather than a
live model on purpose: this suite's job is to pin the pipeline's
OWN behavior (thresholds, validation, gating) against known-correct
input/output pairs, not to grade a live LLM's extraction quality
(that's a separate, live-only concern -- see live_integration_check.py
and the round-2 writeup's note on this exact distinction).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest

from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.workflow.pipeline import BoxMetadataWritebackPipeline


@dataclass
class GoldenCase:
    name: str
    source_text: bytes
    expected_doc_class: str
    expected_retention_category: str
    # Fields expected to land in Box metadata (i.e. cleared review).
    # A field genuinely absent from the source is simply omitted here
    # -- checked separately via expected_missing.
    expected_fields: dict[str, str] = field(default_factory=dict)
    # Fields the source doesn't state at all -- must stay unwritten,
    # proving "left empty rather than guessed."
    expected_missing: list[str] = field(default_factory=list)
    # Fields expected to be held for human review rather than written
    # straight through (below-threshold confidence in the fake model).
    expected_queued_for_review: list[str] = field(default_factory=list)


GOLDEN_CASES = [
    GoldenCase(
        name="clean_services_contract",
        source_text=b"""SERVICES AGREEMENT
Counterparty: Acme Logistics Inc
Effective Date: 2026-01-15
Expiration Date: 2027-01-14
Value: $84,000
""",
        expected_doc_class="contract",
        expected_retention_category="contracts-7yr",
        expected_fields={
            "counterparty_name": "Acme Logistics Inc",
            "effective_date": "2026-01-15",
            "expiration_date": "2027-01-14",
        },
        expected_queued_for_review=["contract_value"],  # fake model's monetary confidence is below threshold
    ),
    GoldenCase(
        name="invoice_with_only_amount",
        source_text=b"INVOICE\nAmount Due: $500\n",
        expected_doc_class="invoice",
        expected_retention_category="financial-5yr",
        # This source has none of counterparty/effective_date/expiration_date/
        # contract_value in the format the extractor recognizes -- every
        # one of those fields should stay honestly empty, not guessed.
        expected_missing=["counterparty_name", "effective_date", "expiration_date", "contract_value"],
    ),
    GoldenCase(
        name="unlabeled_free_text_has_nothing_extractable",
        source_text=b"Some unstructured notes with no recognizable document markers in them.\n",
        expected_doc_class="unknown",
        expected_retention_category="uncategorized-review",
        expected_missing=["counterparty_name", "effective_date", "expiration_date", "contract_value"],
    ),
    GoldenCase(
        name="policy_document",
        source_text=b"COMPANY POLICY\nThis policy governs data retention practices.\n",
        expected_doc_class="policy",
        expected_retention_category="policy-indefinite",
        expected_missing=["counterparty_name", "effective_date", "expiration_date", "contract_value"],
    ),
    GoldenCase(
        name="amendment_with_full_fields",
        source_text=b"""AMENDMENT TO SERVICES AGREEMENT
Counterparty: Globex Corp
Effective Date: 2026-06-01
Expiration Date: 2027-05-31
Value: $12,500
""",
        expected_doc_class="amendment",
        expected_retention_category="contracts-7yr",
        expected_fields={
            "counterparty_name": "Globex Corp",
            "effective_date": "2026-06-01",
            "expiration_date": "2027-05-31",
        },
        expected_queued_for_review=["contract_value"],
    ),
    GoldenCase(
        name="correspondence_letter",
        source_text=b"Dear Counterparty,\n\nThank you for your continued partnership.\n\nRegards,\nThe Company\n",
        expected_doc_class="correspondence",
        expected_retention_category="correspondence-3yr",
        expected_missing=["counterparty_name", "effective_date", "expiration_date", "contract_value"],
    ),
]


def _run_case(case: GoldenCase):
    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    pipeline = BoxMetadataWritebackPipeline(box, sd, retry_sleep_fn=lambda s: None)
    box.seed_file(case.name, f"{case.name}.txt", case.source_text)
    report = pipeline.process(case.name)
    return report, pipeline


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[c.name for c in GOLDEN_CASES])
def test_golden_document_doc_class(case: GoldenCase):
    report, _ = _run_case(case)
    assert report.extracted.doc_class.value == case.expected_doc_class, (
        f"{case.name}: expected doc_class={case.expected_doc_class!r}, "
        f"got {report.extracted.doc_class.value!r}"
    )


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[c.name for c in GOLDEN_CASES])
def test_golden_document_retention_category(case: GoldenCase):
    report, _ = _run_case(case)
    assert report.metadata_written.get("retention_category") == case.expected_retention_category, (
        f"{case.name}: expected retention_category={case.expected_retention_category!r}, "
        f"got {report.metadata_written.get('retention_category')!r}"
    )


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[c.name for c in GOLDEN_CASES])
def test_golden_document_expected_fields_written(case: GoldenCase):
    report, _ = _run_case(case)
    for field_name, expected_value in case.expected_fields.items():
        actual = report.metadata_written.get(field_name)
        assert actual == expected_value, (
            f"{case.name}: field {field_name} expected {expected_value!r}, got {actual!r}"
        )


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[c.name for c in GOLDEN_CASES])
def test_golden_document_missing_fields_stay_honestly_absent(case: GoldenCase):
    report, _ = _run_case(case)
    for field_name in case.expected_missing:
        assert field_name not in report.metadata_written, (
            f"{case.name}: field {field_name} should be absent (source doesn't state it) "
            f"but metadata_written has {report.metadata_written.get(field_name)!r}"
        )


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[c.name for c in GOLDEN_CASES])
def test_golden_document_review_queue_gating(case: GoldenCase):
    report, pipeline = _run_case(case)
    pending_field_names = {r.field_name for r in pipeline.review_queue.list_pending(file_id=case.name)}
    assert pending_field_names == set(case.expected_queued_for_review), (
        f"{case.name}: expected queued-for-review fields {set(case.expected_queued_for_review)}, "
        f"got {pending_field_names}"
    )


def test_golden_suite_covers_every_doc_class():
    """Meta-test: catches someone adding a new DocClass to the model
    without adding a corresponding golden case for it -- the suite
    losing coverage silently is itself a regression worth catching."""
    from app.models import DocClass

    covered = {c.expected_doc_class for c in GOLDEN_CASES}
    all_classes = {dc.value for dc in DocClass}
    assert covered == all_classes, f"golden suite missing coverage for: {all_classes - covered}"
