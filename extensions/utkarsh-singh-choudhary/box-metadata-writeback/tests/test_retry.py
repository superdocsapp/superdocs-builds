from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.workflow.pipeline import BoxMetadataWritebackPipeline
from app.workflow.retry import call_with_retry, is_retryable
from app.clients.superdocs_client import SuperDocsAPIError

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


def test_is_retryable_recognizes_transient_markers_only():
    assert is_retryable(SuperDocsAPIError("simulated SuperDocs outage")) is True
    assert is_retryable(SuperDocsAPIError("connection reset")) is True
    assert is_retryable(SuperDocsAPIError("timeout waiting for response")) is True
    assert is_retryable(SuperDocsAPIError("malformed request: missing document_id")) is False


def test_is_retryable_prefers_real_http_status_code_when_present():
    """RealSuperDocsClient sets status_code from the actual HTTP
    response. When it's present, classification must be status-based,
    not text-based -- e.g. a 429 body that happens not to contain the
    word "timeout" must still be retried, and a 400 body that happens
    to contain the word "connection" (e.g. quoting the user's own bad
    input) must NOT be retried just because of that word."""
    assert is_retryable(SuperDocsAPIError("rate limited", status_code=429)) is True
    assert is_retryable(SuperDocsAPIError("bad gateway", status_code=502)) is True
    assert is_retryable(SuperDocsAPIError("service unavailable", status_code=503)) is True
    assert is_retryable(SuperDocsAPIError("gateway timeout", status_code=504)) is True
    assert is_retryable(SuperDocsAPIError("internal error", status_code=500)) is True
    # Non-transient 4xx: retrying can't fix a bad request or an auth failure.
    assert is_retryable(SuperDocsAPIError("bad request", status_code=400)) is False
    assert is_retryable(SuperDocsAPIError("unauthorized", status_code=401)) is False
    assert is_retryable(SuperDocsAPIError("forbidden", status_code=403)) is False
    assert is_retryable(SuperDocsAPIError("not found", status_code=404)) is False
    # Status code wins over message content even when the message text
    # would otherwise match/mismatch a substring marker.
    assert (
        is_retryable(SuperDocsAPIError("field 'connection_id' invalid", status_code=400)) is False
    )
    assert is_retryable(SuperDocsAPIError("rate limit exceeded", status_code=429)) is True


def test_call_with_retry_recovers_within_budget():
    attempts_made = []

    def flaky():
        attempts_made.append(1)
        if len(attempts_made) < 2:
            raise SuperDocsAPIError("simulated SuperDocs outage")
        return "ok"

    result = call_with_retry(flaky, max_attempts=3, base_delay=0, sleep_fn=lambda s: None)
    assert result.value == "ok"
    assert result.attempts == 2


def test_call_with_retry_gives_up_after_max_attempts():
    import pytest

    def always_fails():
        raise SuperDocsAPIError("simulated SuperDocs outage")

    with pytest.raises(SuperDocsAPIError) as exc_info:
        call_with_retry(always_fails, max_attempts=3, base_delay=0, sleep_fn=lambda s: None)
    assert exc_info.value.attempts == 3  # type: ignore[attr-defined]


def test_call_with_retry_does_not_retry_non_transient_errors():
    attempts_made = []

    def fails_permanently():
        attempts_made.append(1)
        raise SuperDocsAPIError("malformed request: bad document_id")

    import pytest

    with pytest.raises(SuperDocsAPIError):
        call_with_retry(fails_permanently, max_attempts=3, base_delay=0, sleep_fn=lambda s: None)
    assert len(attempts_made) == 1  # no retry attempted on a non-transient error


def test_pipeline_stage_recovers_from_one_transient_blip():
    box, sd, pipeline = make_pipeline()
    box.seed_file("f1", "acme-msa.pdf", CONTRACT_TEXT)
    sd.force_next_n_failures(1)  # classify's first attempt fails, second succeeds

    report = pipeline.process("f1")

    stage_status = {s.name: s.status for s in report.stages}
    assert stage_status["classify"] == "done"
    classify_stage = next(s for s in report.stages if s.name == "classify")
    assert classify_stage.operations == 2  # 1 failed attempt + 1 successful attempt, both billed
    assert "succeeded after 2 attempts" in classify_stage.detail
    # the run completes normally despite the blip
    assert report.metadata_written["doc_class"] == "contract"


def test_pipeline_stage_exhausts_retries_and_fails_honestly():
    box, sd, pipeline = make_pipeline(max_retry_attempts=2)
    box.seed_file("f2", "acme-msa.pdf", CONTRACT_TEXT)
    sd.force_next_n_failures(5)  # more failures than the retry budget

    report = pipeline.process("f2")

    stage_status = {s.name: s.status for s in report.stages}
    assert stage_status["classify"] == "failed"
    classify_stage = next(s for s in report.stages if s.name == "classify")
    assert classify_stage.operations == 2  # exhausted the configured max, no more
    assert "failed after 2 attempts" in classify_stage.detail
