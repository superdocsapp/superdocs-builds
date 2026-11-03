"""Circuit breaker (SuperDocs-outage fail-fast), dead-letter queue
(ops worklist for runs a stage couldn't make progress on), and
per-field review-queue thresholds -- the round-3 "make it production
elite" additions.
"""
import time

from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.workflow.dead_letter import DeadLetterQueue
from app.workflow.pipeline import BoxMetadataWritebackPipeline
from app.workflow.retry import CircuitBreaker, CircuitOpenError, call_with_retry
from app.workflow.review_queue import ReviewQueue

CONTRACT_TEXT = b"""SERVICES AGREEMENT
Counterparty: Acme Logistics Inc
Effective Date: 2026-01-15
Value: $84,000
"""


def make_pipeline(**kwargs):
    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    pipeline = BoxMetadataWritebackPipeline(box, sd, retry_sleep_fn=lambda s: None, **kwargs)
    return box, sd, pipeline


# --- CircuitBreaker unit behavior -------------------------------------------


def test_breaker_stays_closed_under_threshold():
    breaker = CircuitBreaker(failure_threshold=3, reset_after_seconds=10)
    for _ in range(2):
        breaker.before_call()  # must not raise
        breaker.record_failure()
    assert breaker.is_open is False


def test_breaker_opens_at_threshold_and_fails_fast():
    breaker = CircuitBreaker(failure_threshold=3, reset_after_seconds=10)
    for _ in range(3):
        breaker.record_failure()
    assert breaker.is_open is True
    try:
        breaker.before_call()
        assert False, "expected CircuitOpenError"
    except CircuitOpenError:
        pass


def test_breaker_half_opens_after_reset_window_and_a_success_closes_it():
    fake_now = [0.0]
    breaker = CircuitBreaker(failure_threshold=2, reset_after_seconds=5, clock=lambda: fake_now[0])
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.is_open is True
    fake_now[0] += 5.1  # past the reset window: half-open, one trial call allowed
    breaker.before_call()  # must not raise now
    breaker.record_success()
    assert breaker.is_open is False
    # failure count reset by the success -- a single subsequent failure
    # should NOT reopen it (threshold is 2)
    breaker.record_failure()
    assert breaker.is_open is False


def test_breaker_call_wrapper_records_success_and_failure():
    breaker = CircuitBreaker(failure_threshold=1, reset_after_seconds=10)
    with __import__("pytest").raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert breaker.is_open is True


# --- Circuit breaker wired into the pipeline --------------------------------


def test_pipeline_trips_breaker_after_consecutive_exhausted_retries_and_fails_fast():
    box, sd, pipeline = make_pipeline(
        max_retry_attempts=1,  # exhaust immediately on first failure
        circuit_breaker=CircuitBreaker(failure_threshold=2, reset_after_seconds=999),
    )
    # Two separate files, each permanently failing classify -> two
    # consecutive breaker-recorded failures -> breaker opens.
    for i in range(2):
        f = f"contract-{i}"
        box.seed_file(f, f"contract-{i}.txt", CONTRACT_TEXT)
        sd.force_next_failure()
        pipeline.process(f)

    assert pipeline.circuit_breaker.is_open is True

    # A third file's classify stage should never even reach SuperDocs --
    # the breaker fails fast, which the fake client's call log proves
    # (no new chat() call recorded for this file).
    f3 = "contract-3"
    box.seed_file(f3, "contract-3.txt", CONTRACT_TEXT)
    calls_before = len(sd.call_log)
    report = pipeline.process(f3)
    assert len(sd.call_log) == calls_before  # no live call was attempted
    classify_stage = next(s for s in report.stages if s.name == "classify")
    assert classify_stage.status == "failed"
    assert "circuit open" in classify_stage.detail.lower()


def test_pipeline_breaker_resets_on_a_success_between_failures():
    box, sd, pipeline = make_pipeline(
        max_retry_attempts=1,
        circuit_breaker=CircuitBreaker(failure_threshold=2, reset_after_seconds=999),
    )
    f1 = "c1"
    box.seed_file(f1, "c1.txt", CONTRACT_TEXT)
    sd.force_next_failure()
    pipeline.process(f1)  # 1 failure recorded

    f2 = "c2"
    box.seed_file(f2, "c2.txt", CONTRACT_TEXT)
    pipeline.process(f2)  # succeeds -> resets failure count to 0

    f3 = "c3"
    box.seed_file(f3, "c3.txt", CONTRACT_TEXT)
    sd.force_next_failure()
    pipeline.process(f3)  # 1 failure again, still below threshold of 2
    assert pipeline.circuit_breaker.is_open is False


# --- Dead-letter queue -------------------------------------------------------


def test_dead_letter_queue_add_list_resolve():
    dlq = DeadLetterQueue()
    entry = dlq.add(file_id="f1", version_sha1="abc123", stage="classify", reason="boom", attempts=3)
    assert entry.resolved is False
    pending = dlq.list_unresolved()
    assert len(pending) == 1 and pending[0].entry_id == entry.entry_id

    resolved = dlq.resolve(entry.entry_id)
    assert resolved.resolved is True
    assert dlq.list_unresolved() == []


def test_dead_letter_queue_filters_by_file_id():
    dlq = DeadLetterQueue()
    dlq.add(file_id="f1", version_sha1="a", stage="classify", reason="x", attempts=1)
    dlq.add(file_id="f2", version_sha1="b", stage="extract", reason="y", attempts=1)
    assert len(dlq.list_unresolved(file_id="f1")) == 1
    assert len(dlq.list_unresolved(file_id="f2")) == 1
    assert len(dlq.list_unresolved()) == 2


def test_a_run_with_a_permanently_failed_stage_lands_in_the_dead_letter_queue():
    box, sd, pipeline = make_pipeline(max_retry_attempts=1)
    f = "contract"
    box.seed_file(f, "contract.txt", CONTRACT_TEXT)
    sd.force_next_failure()
    report = pipeline.process(f)
    # graceful degradation: the run still commits (README behavior #6)
    assert report.skipped_reason is None
    entries = pipeline.dead_letter.list_unresolved(file_id=f)
    assert len(entries) == 1
    assert entries[0].stage == "classify"


def test_a_fully_successful_run_never_touches_the_dead_letter_queue():
    box, sd, pipeline = make_pipeline()
    f = "contract"
    box.seed_file(f, "contract.txt", CONTRACT_TEXT)
    pipeline.process(f)
    assert pipeline.dead_letter.list_unresolved() == []


# --- Per-field review thresholds ---------------------------------------------


def test_review_queue_default_threshold_applies_when_no_override():
    rq = ReviewQueue(threshold=0.7)
    assert rq.threshold_for("counterparty_name") == 0.7
    assert rq.requires_review("counterparty_name", 0.65) is True
    assert rq.requires_review("counterparty_name", 0.75) is False


def test_review_queue_per_field_override_wins_over_default():
    rq = ReviewQueue(threshold=0.7, field_thresholds={"contract_value": 0.9})
    # contract_value uses the tighter 0.9 bar
    assert rq.requires_review("contract_value", 0.85) is True
    # a field with no override still uses the 0.7 default
    assert rq.requires_review("counterparty_name", 0.75) is False


def test_pipeline_gates_a_field_by_its_own_per_field_threshold():
    rq = ReviewQueue(threshold=0.5, field_thresholds={"contract_value": 0.95})
    box, sd, pipeline = make_pipeline(review_queue=rq)
    f = "contract"
    box.seed_file(f, "contract.txt", CONTRACT_TEXT)
    report = pipeline.process(f)
    # contract_value's confidence in the fake extractor (0.55) clears the
    # global 0.5 default but not the field-specific 0.95 override, so it
    # must be queued for review rather than written straight to metadata.
    pending_fields = {r.field_name for r in rq.list_pending(file_id=f)}
    assert "contract_value" in pending_fields
