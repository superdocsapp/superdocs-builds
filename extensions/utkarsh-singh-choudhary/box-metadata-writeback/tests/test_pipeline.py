import threading

import pytest

from app.clients.box_client import BoxAPIError
from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.models import GovernanceState
from app.workflow.idempotency import IdempotencyStore
from app.workflow.pipeline import BoxMetadataWritebackPipeline

CONTRACT_TEXT = b"""SERVICES AGREEMENT
Counterparty: Acme Logistics Inc
Effective Date: 2026-01-15
Expiration Date: 2027-01-14
Value: $84,000
This agreement governs the provision of freight brokerage services.
"""

INCOMPLETE_CONTRACT_TEXT = b"""SERVICES AGREEMENT
This is a contract but does not state a counterparty, dates, or value
anywhere in its text.
"""


def make_pipeline():
    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    # no-op sleep: retry backoff logic is exercised for real (attempt
    # counts, thresholds), but tests don't have to actually wait for it
    pipeline = BoxMetadataWritebackPipeline(box, sd, retry_sleep_fn=lambda seconds: None)
    return box, sd, pipeline


def test_happy_path_populates_metadata_and_generates_companion():
    box, sd, pipeline = make_pipeline()
    box.seed_file("file-1", "acme-msa.pdf", CONTRACT_TEXT)

    report = pipeline.process("file-1")

    assert report.skipped_reason is None
    assert [s.status for s in report.stages] == ["done", "done", "done", "done", "done"]
    md = report.metadata_written
    assert md["doc_class"] == "contract"
    assert md["counterparty_name"] == "Acme Logistics Inc"
    assert md["effective_date"] == "2026-01-15"
    # contract_value comes back at confidence 0.55, below the 0.7 review
    # threshold, so it is held for human review rather than auto-written --
    # see test_low_confidence_field_is_queued_for_review_not_auto_written.
    assert "contract_value" not in md
    assert md["normalized"] is True
    assert "companion_document_id" in md
    # companion doc genuinely exists in Box now, as a real .docx (not
    # plain text) -- verify it opens and carries the generated content.
    companion_bytes = box.download_file(md["companion_document_id"])
    assert companion_bytes.startswith(b"PK")  # docx = a zip archive
    import io as _io

    from docx import Document as _Document

    companion_doc = _Document(_io.BytesIO(companion_bytes))
    full_text = "\n".join(p.text for p in companion_doc.paragraphs)
    assert "COMPANION SUMMARY" in full_text


def test_fields_the_document_does_not_state_are_left_empty_not_guessed():
    box, sd, pipeline = make_pipeline()
    box.seed_file("file-2", "vague-contract.pdf", INCOMPLETE_CONTRACT_TEXT)

    report = pipeline.process("file-2")

    md = report.metadata_written
    assert md["doc_class"] == "contract"
    # None of these keys should be present at all -- absent, not null,
    # not a placeholder string.
    for key in ("counterparty_name", "effective_date", "expiration_date", "contract_value"):
        assert key not in md
    assert "source did not support" in md["extraction_notes"]


def test_legal_hold_blocks_all_processing_and_no_superdocs_call_is_made():
    box, sd, pipeline = make_pipeline()
    box.seed_file(
        "file-3", "litigation-hold.pdf", CONTRACT_TEXT,
        governance=GovernanceState(legal_hold=True),
    )

    report = pipeline.process("file-3")

    assert report.skipped_reason is not None
    assert "legal hold" in report.skipped_reason
    assert report.metadata_written == {}
    # No SuperDocs doc was ever created for this file -- proves we bailed
    # out before calling the API at all, not just before writing metadata.
    assert len(sd._docs) == 0


def test_retention_lock_also_blocks_processing():
    box, sd, pipeline = make_pipeline()
    box.seed_file(
        "file-4", "locked.pdf", CONTRACT_TEXT,
        governance=GovernanceState(retention_policy_locked=True),
    )
    report = pipeline.process("file-4")
    assert report.skipped_reason is not None
    assert box.get_metadata("file-4", "documentIntelligence") == {}


def test_governance_keys_can_never_be_written_even_if_pipeline_tried():
    box, sd, pipeline = make_pipeline()
    box.seed_file("file-5", "x.pdf", CONTRACT_TEXT)
    with pytest.raises(BoxAPIError):
        box.update_metadata("file-5", "documentIntelligence", {"legal_hold": False})


def test_idempotent_per_file_version_same_bytes_reprocess_is_a_noop():
    box, sd, pipeline = make_pipeline()
    box.seed_file("file-6", "msa.pdf", CONTRACT_TEXT)

    first = pipeline.process("file-6")
    assert first.skipped_reason is None

    second = pipeline.process("file-6")
    assert second.skipped_reason == "already processed this exact file version"
    # Metadata from the first run is untouched, not re-written
    assert second.metadata_written == {}


def test_new_version_of_same_file_is_reprocessed():
    box, sd, pipeline = make_pipeline()
    box.seed_file("file-7", "msa.pdf", INCOMPLETE_CONTRACT_TEXT, version_id="1")
    first = pipeline.process("file-7")
    assert "counterparty_name" not in first.metadata_written

    box.bump_version("file-7", CONTRACT_TEXT, version_id="2")
    second = pipeline.process("file-7")
    assert second.skipped_reason is None
    assert second.metadata_written["counterparty_name"] == "Acme Logistics Inc"


def test_concurrent_processing_of_the_same_file_does_not_corrupt_state():
    box, sd, pipeline = make_pipeline()
    box.seed_file("file-8", "msa.pdf", CONTRACT_TEXT)

    results = []

    def run():
        results.append(pipeline.process("file-8"))

    threads = [threading.Thread(target=run) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    processed = [r for r in results if r.skipped_reason is None]
    skipped = [r for r in results if r.skipped_reason is not None]
    # Exactly one thread should have actually done the work; the rest
    # observe either the concurrency claim or the idempotency check.
    assert len(processed) == 1
    assert len(skipped) == 4
    assert processed[0].metadata_written["counterparty_name"] == "Acme Logistics Inc"


def test_graceful_degradation_on_superdocs_outage_during_extract():
    box, sd, pipeline = make_pipeline()
    box.seed_file("file-9", "msa.pdf", CONTRACT_TEXT)

    # classify succeeds, then force the extract call to fail
    def chat_wrapper(document_id, instruction):
        if "extract key terms" in instruction.lower():
            sd.force_next_failure()
        return orig_chat(document_id, instruction)

    orig_chat = sd.chat
    sd.chat = chat_wrapper  # type: ignore[method-assign]

    report = pipeline.process("file-9")

    stage_status = {s.name: s.status for s in report.stages}
    assert stage_status["classify"] == "done"
    assert stage_status["extract"] == "failed"
    # retried up to the configured max (3) before giving up, and the
    # retry attempts are honestly reflected in operations spent
    extract_stage = next(s for s in report.stages if s.name == "extract")
    assert extract_stage.operations == 3
    assert "failed after 3 attempts" in extract_stage.detail
    # Run does not crash; partial honest state is still committed
    assert report.metadata_written["doc_class"] == "contract"
    assert "extraction unavailable after 3 attempt(s)" in report.metadata_written["extraction_notes"]
    # No counterparty guessed despite the outage
    assert "counterparty_name" not in report.metadata_written


def test_correspondence_does_not_get_a_companion_document():
    box, sd, pipeline = make_pipeline()
    box.seed_file("file-10", "email.pdf", b"Dear team, following up on the policy update.")
    report = pipeline.process("file-10")
    stage_status = {s.name: s.status for s in report.stages}
    assert stage_status["generate_companion"] == "skipped"
    assert "companion_document_id" not in report.metadata_written


def test_policy_document_classified_correctly_even_when_it_mentions_agreement_in_passing():
    """Regression test for a real bug found via the realistic demo
    scenario: a policy document that says 'not a client-facing
    agreement' was misclassified as a contract, because the fake
    classifier's keyword match doesn't understand negation and
    'agreement' matched before 'policy' got a chance to. Fixed by
    checking for 'policy' before 'agreement'/'contract' -- a policy
    title is a much stronger signal than an incidental word inside a
    sentence, so this ordering is the right general fix, not a
    one-document patch."""
    box, sd, pipeline = make_pipeline()
    box.seed_file(
        "file-11", "policy.pdf",
        b"COLD CHAIN COMPLIANCE POLICY\n\nThis is an internal governance document, "
        b"not a client-facing agreement, and does not carry a counterparty.",
    )
    report = pipeline.process("file-11")
    assert report.metadata_written["doc_class"] == "policy"
    # policy docs never get a companion document
    assert "companion_document_id" not in report.metadata_written


def test_failed_run_does_not_permanently_block_retry():
    """Regression test: a run that fails partway through (e.g. the
    classify stage) must NOT be marked as a completed version. Before
    this fix, `process()` unconditionally called
    `idempotency.release(file_id, version.sha1)` in its `finally`
    block -- including on the early-return failure paths -- which wrote
    the failed sha1 into the 'done' set. A second call to process() for
    the exact same file version would then be skipped forever via
    `already_processed()`, even though the first run never wrote
    complete metadata. Correct behavior: the claim is released so
    another attempt is possible, but the version is only marked done
    after a genuinely successful `_commit_final`."""
    box, sd, pipeline = make_pipeline()
    box.seed_file("file-99", "acme-msa.pdf", CONTRACT_TEXT)
    # Exhaust the classify stage's retry budget (DEFAULT_MAX_ATTEMPTS=3)
    # so the first run genuinely fails rather than transparently
    # recovering via retry -- then stop forcing failures so the second
    # run (the retry we're actually testing) succeeds cleanly.
    sd.force_next_n_failures(3)

    first = pipeline.process("file-99")
    stage_status = {s.name: s.status for s in first.stages}
    assert stage_status["classify"] == "failed"
    assert first.metadata_written.get("doc_class") in (None, "unknown")

    # The exact same (file_id, sha1) must be retryable, not silently
    # skipped as "already processed".
    assert pipeline.idempotency.already_processed("file-99", first.version_sha1) is False

    second = pipeline.process("file-99")
    assert second.skipped_reason is None
    assert second.metadata_written["doc_class"] == "contract"
    assert second.metadata_written["counterparty_name"] == "Acme Logistics Inc"

    # Now that it genuinely succeeded, it IS marked done.
    assert pipeline.idempotency.already_processed("file-99", second.version_sha1) is True
