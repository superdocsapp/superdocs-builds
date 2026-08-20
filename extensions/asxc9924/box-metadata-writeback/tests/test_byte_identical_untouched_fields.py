"""tests/test_review_and_history.py already proves the audit trail
doesn't LOG an unchanged field again on reprocess. That's a weaker
claim than "surgical precision. Change what you meant to change and
nothing else, and be able to show that nothing else changed" -- a
missing log entry is consistent with the value having silently drifted
as long as nobody happened to check. This file proves the stronger,
literal claim directly against Box's own stored metadata dict: capture
the exact value of every field before a reprocess, and after
reprocessing on a new file version that only changes ONE fact, assert
every other field's value is `==` to what it was before -- not
"wasn't logged as different," but is actually, byte-for-byte, the same
value in the same dict.
"""
from __future__ import annotations

from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.workflow.history_store import MetadataHistoryStore
from app.workflow.pipeline import BoxMetadataWritebackPipeline
from app.workflow.review_queue import ReviewQueue


def make_pipeline():
    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    rq = ReviewQueue()
    hist = MetadataHistoryStore()
    pipeline = BoxMetadataWritebackPipeline(box, sd, review_queue=rq, history=hist)
    return box, sd, pipeline, rq, hist


def test_untouched_fields_are_byte_identical_after_reprocess_on_new_version():
    box, sd, pipeline, rq, hist = make_pipeline()
    box.seed_file(
        "f-byte-1",
        "msa.pdf",
        b"SERVICES AGREEMENT\nCounterparty: Riverstone Analytics LLC\nEffective Date: 2023-02-01\n",
        version_id="1",
    )
    pipeline.process("f-byte-1")
    before = box.get_metadata("f-byte-1", "documentIntelligence")
    assert before["counterparty_name"] == "Riverstone Analytics LLC"
    assert before["effective_date"] == "2023-02-01"

    # bump to a version where ONLY expiration_date is newly stated;
    # counterparty_name and effective_date are repeated verbatim
    box.bump_version(
        "f-byte-1",
        b"SERVICES AGREEMENT\nCounterparty: Riverstone Analytics LLC\n"
        b"Effective Date: 2023-02-01\nExpiration Date: 2025-02-01\n",
        version_id="2",
    )
    pipeline.process("f-byte-1")
    after = box.get_metadata("f-byte-1", "documentIntelligence")

    # the one fact that changed
    assert after["expiration_date"] == "2025-02-01"
    assert "expiration_date" not in before

    # everything the second run didn't have new information about is
    # not just "the same class of value" -- it is the exact same value,
    # proven by direct equality against the captured baseline, field by
    # field, not by absence from a diff log.
    for key in ("counterparty_name", "effective_date", "doc_class", "retention_category"):
        assert after[key] == before[key], (
            f"{key} drifted on reprocess: {before[key]!r} -> {after[key]!r}"
        )


def test_untouched_fields_are_byte_identical_across_a_low_confidence_review_approval():
    """Same proof, different trigger: approving one held-back
    low-confidence field is documented as "a surgical patch, not a
    full re-run" -- confirm every other field's value is untouched by
    that write, not just that the history entry names only one field."""
    box, sd, pipeline, rq, hist = make_pipeline()
    box.seed_file(
        "f-byte-2",
        "msa.pdf",
        b"SERVICES AGREEMENT\nCounterparty: Delacroix Freight Partners\n"
        b"Effective Date: 2024-01-01\nValue: $30,000\n",
    )
    pipeline.process("f-byte-2")
    before = box.get_metadata("f-byte-2", "documentIntelligence")
    assert "contract_value" not in before  # held back, below the confidence threshold
    pending = rq.list_pending("f-byte-2")
    assert len(pending) == 1

    pipeline.apply_review_decision(pending[0].review_id, approve=True)
    after = box.get_metadata("f-byte-2", "documentIntelligence")

    assert after["contract_value"] == pending[0].proposed_value
    for key in before:
        assert after[key] == before[key], f"{key} drifted after an unrelated field's review approval"
