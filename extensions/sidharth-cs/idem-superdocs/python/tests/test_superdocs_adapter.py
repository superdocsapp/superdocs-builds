"""The adapter's one job: decide whether a failure was sent, and hand the table
a status it can match. Runs with no network and no key."""

from __future__ import annotations

import socket
import ssl
import urllib.error

import pytest

from idem import Policy, Verdict
from idem.superdocs import ApiError, SuperDocs, _shape
from tests.vectorlib import POLICY_PATH


def _http_error(code, headers=None):
    return urllib.error.HTTPError("http://x", code, "reason", headers or {}, None)


@pytest.mark.parametrize(
    "raw,expected_status,expected_sent",
    [
        (_http_error(409), 409, True),
        (_http_error(422), 422, True),
        (_http_error(503), 503, True),
        (urllib.error.URLError(ConnectionRefusedError("refused")), None, False),
        (urllib.error.URLError(socket.gaierror("no such host")), None, False),
        (urllib.error.URLError(ssl.SSLCertVerificationError("bad cert")), None, False),
        (urllib.error.URLError(ssl.SSLError("handshake failed")), None, False),
        (urllib.error.URLError(TimeoutError("timed out")), None, True),
        (urllib.error.URLError(socket.timeout("timed out")), None, True),
        (RuntimeError("something else entirely"), None, True),
    ],
)
def test_sent_is_judged_correctly(raw, expected_status, expected_sent):
    shaped = _shape(raw)
    assert shaped.status == expected_status
    assert shaped.sent is expected_sent


def test_a_failed_tls_handshake_is_never_sent():
    """Found by a live run: the handshake failed on a certificate error, and the
    adapter called it sent. The library then refused an operation that could not
    possibly have happened. Safe, but wrong — no bytes of the request were ever
    written, so this belongs with connection-refused, not with a timeout."""
    shaped = _shape(urllib.error.URLError(ssl.SSLCertVerificationError("bad cert")))
    assert shaped.sent is False

    policy = Policy.load(POLICY_PATH)
    assert policy.classify(status=None, error="ApiError", sent=shaped.sent).outcome == "retryable"


def test_a_timeout_is_assumed_sent():
    """urllib cannot tell a connect timeout from a read timeout, so the adapter
    fails closed. A refused retry the caller can reconcile is recoverable; a
    duplicate metered edit is not."""
    assert _shape(urllib.error.URLError(TimeoutError())).sent is True


def test_shaped_errors_classify_as_intended():
    """End to end: a real urllib failure, through the adapter, into the table."""
    policy = Policy.load(POLICY_PATH)

    def outcome(raw):
        shaped = _shape(raw)
        return policy.classify(
            status=shaped.status, error=type(shaped).__name__, sent=shaped.sent
        ).outcome

    assert outcome(_http_error(409)) == "terminal"
    assert outcome(_http_error(422)) == "terminal"
    assert outcome(_http_error(503)) == "unknown"
    assert outcome(_http_error(429)) == "retryable"
    assert outcome(urllib.error.URLError(ConnectionRefusedError())) == "retryable"
    assert outcome(urllib.error.URLError(TimeoutError())) == "unknown"


def test_retry_after_is_carried_through():
    shaped = _shape(_http_error(429, {"Retry-After": "3"}))
    assert shaped.retry_after_ms == 3000.0


class _StubJobs(SuperDocs):
    def __init__(self, answer):
        super().__init__("not-a-real-key")
        self._answer = answer

    def get_job(self, job_id):
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


@pytest.mark.parametrize(
    "answer,exists_verdict,settled_verdict",
    [
        ({"job_id": "j", "status": "completed"}, Verdict.APPLIED, Verdict.APPLIED),
        ({"job_id": "j", "status": "failed"}, Verdict.APPLIED, Verdict.APPLIED),
        ({"job_id": "j", "status": "awaiting_approval"}, Verdict.APPLIED, Verdict.INCONCLUSIVE),
        ({"job_id": "j", "status": "in_progress"}, Verdict.APPLIED, Verdict.INCONCLUSIVE),
        (ApiError("gone", status=404, sent=True), Verdict.NOT_APPLIED, Verdict.NOT_APPLIED),
        (ApiError("boom", status=500, sent=True), Verdict.INCONCLUSIVE, Verdict.INCONCLUSIVE),
    ],
)
def test_the_two_probes_answer_different_questions(answer, exists_verdict, settled_verdict):
    """A created job proves chat_async landed. It does not prove an approve
    settled — which is the exact wedge in the evidence, so the probes differ."""
    client = _StubJobs(answer)

    got_exists = client.job_exists_probe("j")
    got_settled = client.job_settled_probe("j")

    assert (got_exists[0] if isinstance(got_exists, tuple) else got_exists) is exists_verdict
    assert (got_settled[0] if isinstance(got_settled, tuple) else got_settled) is settled_verdict
