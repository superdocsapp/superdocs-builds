from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.workflow.history_store import MetadataHistoryStore
from app.workflow.pipeline import BoxMetadataWritebackPipeline
from app.workflow.review_queue import ReviewQueue

CONTRACT_TEXT = b"""SERVICES AGREEMENT
Counterparty: Acme Logistics Inc
Effective Date: 2026-01-15
Expiration Date: 2027-01-14
Value: $84,000
"""


def make_pipeline():
    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    rq = ReviewQueue()
    hist = MetadataHistoryStore()
    pipeline = BoxMetadataWritebackPipeline(box, sd, review_queue=rq, history=hist)
    return box, sd, pipeline, rq, hist


# --- confidence-gated review queue -------------------------------------------

def test_low_confidence_field_is_queued_for_review_not_auto_written():
    box, sd, pipeline, rq, hist = make_pipeline()
    box.seed_file("f1", "acme-msa.pdf", CONTRACT_TEXT)

    report = pipeline.process("f1")

    # contract_value comes back at confidence 0.55 in the fake extractor,
    # below the 0.7 default threshold
    assert "contract_value" not in report.metadata_written
    assert len(report.queued_for_review) == 1

    pending = rq.list_pending("f1")
    assert len(pending) == 1
    assert pending[0].field_name == "contract_value"
    assert pending[0].proposed_value == "$84,000"
    assert pending[0].status == "pending"


def test_approving_a_review_writes_exactly_that_field_and_only_that_field():
    box, sd, pipeline, rq, hist = make_pipeline()
    box.seed_file("f2", "acme-msa.pdf", CONTRACT_TEXT)
    report = pipeline.process("f2")
    review_id = report.queued_for_review[0]

    before = dict(report.metadata_written)
    result = pipeline.apply_review_decision(review_id, approve=True)

    assert result["status"] == "approved"
    md = box.get_metadata("f2", "documentIntelligence")
    assert md["contract_value"] == "$84,000"
    # every other field is exactly what it was before -- a surgical
    # patch, not a full re-run
    for key, value in before.items():
        assert md[key] == value


def test_rejecting_a_review_never_writes_the_field():
    box, sd, pipeline, rq, hist = make_pipeline()
    box.seed_file("f3", "acme-msa.pdf", CONTRACT_TEXT)
    report = pipeline.process("f3")
    review_id = report.queued_for_review[0]

    result = pipeline.apply_review_decision(review_id, approve=False)
    assert result["status"] == "rejected"
    md = box.get_metadata("f3", "documentIntelligence")
    assert "contract_value" not in md


def test_double_deciding_the_same_review_raises():
    import pytest

    box, sd, pipeline, rq, hist = make_pipeline()
    box.seed_file("f4", "acme-msa.pdf", CONTRACT_TEXT)
    report = pipeline.process("f4")
    review_id = report.queued_for_review[0]

    pipeline.apply_review_decision(review_id, approve=True)
    with pytest.raises(ValueError):
        pipeline.apply_review_decision(review_id, approve=False)


# --- metadata audit trail -----------------------------------------------------

def test_history_records_only_fields_that_actually_changed():
    box, sd, pipeline, rq, hist = make_pipeline()
    box.seed_file("f5", "acme-msa.pdf", CONTRACT_TEXT)

    report1 = pipeline.process("f5")
    entries1 = hist.get_history("f5")
    # first run: every written field is a "change" from nothing -> value
    written_keys = set(report1.metadata_written.keys())
    assert {e.field_name for e in entries1} == written_keys
    assert all(e.old_value is None for e in entries1)

    # reprocess the exact same version: idempotency should skip it, so no
    # SECOND set of history entries should appear
    pipeline.process("f5")
    assert hist.get_history("f5") == entries1


def test_history_records_only_the_changed_field_when_review_is_approved():
    box, sd, pipeline, rq, hist = make_pipeline()
    box.seed_file("f6", "acme-msa.pdf", CONTRACT_TEXT)
    report = pipeline.process("f6")
    baseline_count = len(hist.get_history("f6"))

    review_id = report.queued_for_review[0]
    pipeline.apply_review_decision(review_id, approve=True)

    entries = hist.get_history("f6")
    new_entries = entries[baseline_count:]
    assert len(new_entries) == 1
    assert new_entries[0].field_name == "contract_value"
    assert new_entries[0].old_value is None
    assert new_entries[0].new_value == "$84,000"
    assert new_entries[0].reason == "review approved"


def test_reprocessing_a_new_version_only_logs_fields_that_actually_differ():
    box, sd, pipeline, rq, hist = make_pipeline()
    box.seed_file("f7", "msa.pdf", b"SERVICES AGREEMENT\nCounterparty: Acme Logistics Inc\n", version_id="1")
    pipeline.process("f7")
    baseline = len(hist.get_history("f7"))

    # bump to a version where counterparty is unchanged but a new
    # effective date is now stated
    box.bump_version(
        "f7",
        b"SERVICES AGREEMENT\nCounterparty: Acme Logistics Inc\nEffective Date: 2026-05-01\n",
        version_id="2",
    )
    pipeline.process("f7")
    new_entries = hist.get_history("f7")[baseline:]
    changed_fields = {e.field_name for e in new_entries}
    # effective_date is new; doc_class/confidence/normalized may also
    # legitimately be re-affirmed depending on the fake model, but
    # counterparty_name must NOT appear again since it didn't change
    assert "effective_date" in changed_fields
    assert "counterparty_name" not in changed_fields
