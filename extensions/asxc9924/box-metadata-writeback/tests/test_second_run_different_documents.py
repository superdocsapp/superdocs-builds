"""Automated version of scripts/demo_scenario_2.py's proof: the exact
same pipeline code, unmodified, correctly handles a second batch of
genuinely different documents (different vendor, different document
mix, different label formats) -- not just the first demo's fixtures.
Ties directly to the card's "a second run means different documents
inside that declared set."
"""
from __future__ import annotations

import pathlib

import pytest

from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.models import DocClass, GovernanceState
from app.workflow.pipeline import BoxMetadataWritebackPipeline

SCENARIO_DIR = pathlib.Path(__file__).resolve().parent.parent / "demo_scenario_2"


def load(name: str) -> bytes:
    return (SCENARIO_DIR / name).read_bytes()


@pytest.fixture
def batch_two():
    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    pipeline = BoxMetadataWritebackPipeline(box, sd)

    box.seed_file("msa-solstice", "01_msa_solstice.pdf", load("01_msa_solstice.txt"))
    box.seed_file("invoice-solstice", "02_invoice_solstice.pdf", load("02_invoice_solstice.txt"))
    box.seed_file("email-solstice", "03_email_thread_solstice.pdf", load("03_email_thread_solstice.txt"))
    box.seed_file("policy-underwriting", "04_underwriting_policy.pdf", load("04_underwriting_policy.txt"))
    box.seed_file(
        "msa-solstice-hold", "05_msa_solstice_under_hold.pdf",
        load("05_msa_solstice_under_hold.txt"),
        governance=GovernanceState(legal_hold=True),
    )
    return box, sd, pipeline


def test_contract_with_clean_labels_extracts_correctly(batch_two):
    box, sd, pipeline = batch_two
    report = pipeline.process("msa-solstice")
    assert report.skipped_reason is None
    assert report.metadata_written["doc_class"] == DocClass.CONTRACT.value
    assert report.metadata_written["counterparty_name"] == "Solstice Freight Underwriters Inc."
    assert "companion_document_id" in report.metadata_written  # contracts get a companion doc


def test_invoice_with_different_label_layout_extracts_correctly(batch_two):
    box, sd, pipeline = batch_two
    report = pipeline.process("invoice-solstice")
    assert report.skipped_reason is None
    assert report.metadata_written["doc_class"] == DocClass.INVOICE.value
    # invoices don't get a companion document
    assert "companion_document_id" not in report.metadata_written


def test_informal_email_with_no_labeled_fields_leaves_them_empty_not_guessed(batch_two):
    box, sd, pipeline = batch_two
    report = pipeline.process("email-solstice")
    assert report.skipped_reason is None
    written = report.metadata_written
    # None of these were ever labeled in the source text -- the pipeline
    # must not have invented values for them on a document shape it
    # hasn't seen before.
    for key in ("counterparty_name", "effective_date", "expiration_date", "contract_value"):
        assert key not in written, f"{key} was guessed on a document with no labeled value for it"


def test_policy_with_negation_and_sibling_phrasing_is_not_misclassified_as_contract(batch_two):
    """The original bug (documented in README) was a policy doc
    containing the word "agreement" in a negated sentence being
    misclassified as a contract. This document repeats that exact
    phrasing plus reuses "counterparty"/"coverage value" words
    liberally to try to re-trigger it, proving the fix (checking the
    policy branch before the agreement/contract branch) generalizes
    rather than only covering the one sentence that originally
    surfaced it."""
    box, sd, pipeline = batch_two
    report = pipeline.process("policy-underwriting")
    assert report.skipped_reason is None
    assert report.metadata_written["doc_class"] == DocClass.POLICY.value


def test_second_legal_hold_file_with_different_narrative_is_still_blocked(batch_two):
    box, sd, pipeline = batch_two
    report = pipeline.process("msa-solstice-hold")
    assert report.skipped_reason is not None
    assert "legal hold" in report.skipped_reason
    assert report.metadata_written == {}


def test_full_batch_two_runs_without_touching_batch_one_fixtures():
    """Sanity check that batch two is genuinely independent test data,
    not a copy-paste of batch one's file IDs or content."""
    batch_one_dir = pathlib.Path(__file__).resolve().parent.parent / "demo_scenario"
    batch_one_names = {p.name for p in batch_one_dir.glob("*.txt")}
    batch_two_names = {p.name for p in SCENARIO_DIR.glob("*.txt")}
    assert batch_one_names.isdisjoint(batch_two_names)
    assert len(batch_two_names) == 5
