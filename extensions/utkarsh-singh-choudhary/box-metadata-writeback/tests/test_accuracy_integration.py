"""End-to-end tests: the accuracy layer wired into the real pipeline,
not just the pure functions in test_accuracy.py. Uses a thin wrapper
around FakeSuperDocsClient to inject specific extraction results
(a hallucinated value, a malformed date, contradictory dates) that the
stock fake client's deterministic-from-source behavior would never
produce on its own -- these are the failure modes the accuracy layer
exists to catch, so the test harness has to be able to produce them.
"""
import json

from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.workflow.pipeline import BoxMetadataWritebackPipeline

CONTRACT_TEXT = b"""SERVICES AGREEMENT
Counterparty: Acme Logistics Inc
Effective Date: 2026-01-15
Expiration Date: 2027-01-14
Value: $84,000
"""


class InjectingSuperDocsClient(FakeSuperDocsClient):
    """Wraps the stock fake client and overrides exactly one field of
    the extract-stage response with an attacker/hallucination-chosen
    value, leaving every other stage (classify, companion, normalize)
    behaving normally."""

    def __init__(self, field_overrides: dict[str, str], confidence_overrides: dict[str, float] = None):
        super().__init__()
        self._field_overrides = field_overrides
        self._confidence_overrides = confidence_overrides or {}

    def chat(self, document_id: str, instruction: str):
        result = super().chat(document_id, instruction)
        if "extract key terms" in instruction.lower() and result.proposed_change:
            change = dict(result.proposed_change)
            fields = dict(change.get("fields", {}))
            confidences = dict(change.get("field_confidence", {}))
            fields.update(self._field_overrides)
            confidences.update(self._confidence_overrides)
            change["fields"] = fields
            change["field_confidence"] = confidences
            result.proposed_change = change
        return result


def make_pipeline(sd):
    box = FakeBoxClient()
    pipeline = BoxMetadataWritebackPipeline(box, sd, retry_sleep_fn=lambda s: None)
    return box, pipeline


def test_hallucinated_value_not_in_source_gets_queued_for_review_despite_high_self_reported_confidence():
    sd = InjectingSuperDocsClient(
        field_overrides={"counterparty_name": "Totally Fabricated Corp"},
        confidence_overrides={"counterparty_name": 0.98},  # model claims high confidence anyway
    )
    box, pipeline = make_pipeline(sd)
    box.seed_file("f1", "contract.txt", CONTRACT_TEXT)
    report = pipeline.process("f1")

    # Never written to metadata despite the model's 0.98 self-reported score
    assert "counterparty_name" not in report.metadata_written
    pending = pipeline.review_queue.list_pending(file_id="f1")
    assert any(r.field_name == "counterparty_name" for r in pending)
    assert "hallucination" in report.extracted.extraction_notes.lower()


def test_genuine_value_from_source_is_not_penalized():
    sd = FakeSuperDocsClient()
    box, pipeline = make_pipeline(sd)
    box.seed_file("f1", "contract.txt", CONTRACT_TEXT)
    report = pipeline.process("f1")
    assert report.metadata_written.get("counterparty_name") == "Acme Logistics Inc"


def test_malformed_date_gets_queued_for_review_despite_high_self_reported_confidence():
    sd = InjectingSuperDocsClient(
        field_overrides={"effective_date": "not-a-real-date"},
        confidence_overrides={"effective_date": 0.95},
    )
    box, pipeline = make_pipeline(sd)
    box.seed_file("f1", "contract.txt", CONTRACT_TEXT)
    report = pipeline.process("f1")

    assert "effective_date" not in report.metadata_written
    pending = pipeline.review_queue.list_pending(file_id="f1")
    assert any(r.field_name == "effective_date" for r in pending)


def test_contradictory_dates_both_get_capped_and_queued():
    sd = InjectingSuperDocsClient(
        field_overrides={"effective_date": "2027-01-14", "expiration_date": "2026-01-15"},
        confidence_overrides={"effective_date": 0.9, "expiration_date": 0.9},
    )
    box, pipeline = make_pipeline(sd)
    box.seed_file("f1", "contract.txt", CONTRACT_TEXT)
    report = pipeline.process("f1")

    assert "effective_date" not in report.metadata_written
    assert "expiration_date" not in report.metadata_written
    assert "before" in report.extracted.extraction_notes.lower()


def test_invalid_currency_gets_queued_for_review():
    sd = InjectingSuperDocsClient(
        field_overrides={"contract_value": "approximately eighty four thousand dollars"},
        confidence_overrides={"contract_value": 0.9},
    )
    box, pipeline = make_pipeline(sd)
    box.seed_file("f1", "contract.txt", CONTRACT_TEXT)
    report = pipeline.process("f1")

    assert "contract_value" not in report.metadata_written
    pending = pipeline.review_queue.list_pending(file_id="f1")
    assert any(r.field_name == "contract_value" for r in pending)


class LowConfidenceClassifySuperDocsClient(FakeSuperDocsClient):
    """Overrides only the classify-stage confidence, leaving doc_class
    itself (and every other stage) untouched -- isolates "shaky
    classification" from "wrong classification"."""

    def chat(self, document_id: str, instruction: str):
        result = super().chat(document_id, instruction)
        if "classify" in instruction.lower() and result.proposed_change:
            change = dict(result.proposed_change)
            change["confidence"] = 0.4  # below DOC_CLASS_CONFIDENCE_FLOOR
            result.proposed_change = change
        return result


def test_low_confidence_classification_forces_retention_category_to_review_fallback():
    sd = LowConfidenceClassifySuperDocsClient()
    box, pipeline = make_pipeline(sd)
    box.seed_file("f1", "contract.txt", CONTRACT_TEXT)
    report = pipeline.process("f1")

    # doc_class itself is still whatever the model said (contract) --
    # only the DERIVED retention category is held back
    assert report.extracted.doc_class.value == "contract"
    assert report.metadata_written.get("retention_category") == "uncategorized-review"
    assert "confidence" in report.extracted.extraction_notes.lower()


def test_high_confidence_classification_uses_the_real_retention_category():
    sd = FakeSuperDocsClient()  # stock fake reports high confidence
    box, pipeline = make_pipeline(sd)
    box.seed_file("f1", "contract.txt", CONTRACT_TEXT)
    report = pipeline.process("f1")
    assert report.metadata_written.get("retention_category") == "contracts-7yr"
