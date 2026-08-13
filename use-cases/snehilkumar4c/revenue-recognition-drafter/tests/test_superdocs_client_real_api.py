"""Real-account tests for the three SuperDocsClient methods that were
built (Day 2) and mock-tested, but never exercised against the real API:
upload_document(), the synchronous chat(), and a genuine SUCCESS case for
cancel_job() (it had only ever been hit once, by accident, against a job
that had already completed -- a real 400, but not the real success path).

Closes items 2 and 3 from the 2026-08-11 gap review, after export() (item
covered separately in tests/test_drafter_publish_real_superdocs.py) turned
up a real bug that mocks alone couldn't have caught. These three, probed
manually first via curl before writing any assertion (same discipline):
upload_document() and chat() both returned response shapes that already
matched what the client code assumes -- no bug, just untested. cancel_job()
successfully cancelled a genuinely in-progress job and the job's status
correctly transitioned to "cancelled" on the next poll.

Gated behind RUN_LIVE_SUPERDOCS_TEST=1 + a real SUPERDOCS_API_KEY, skipped
by default and in CI -- same reasoning as the publish real-account test:
these create real, stateful account resources and aren't cassette-
replayable.
"""

from __future__ import annotations

import os

import pytest

from core.superdocs_client import SuperDocsClient

_api_key = os.environ.get("SUPERDOCS_API_KEY", "")
_run_requested = os.environ.get("RUN_LIVE_SUPERDOCS_TEST") == "1"

pytestmark = pytest.mark.skipif(
    not (_run_requested and _api_key and not _api_key.startswith("sk_...")),
    reason=(
        "Live SuperDocs account test, skipped by default (consumes real "
        "account operations and creates real session state -- not "
        "cassette-replayable). Set RUN_LIVE_SUPERDOCS_TEST=1 with a real "
        "SUPERDOCS_API_KEY to run it."
    ),
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "drafter")


def test_real_upload_document_returns_expected_shape() -> None:
    client = SuperDocsClient(api_key=_api_key)
    try:
        fixture_path = os.path.join(FIXTURES_DIR, "contract_hardware_warranty.txt")
        result = client.upload_document(fixture_path, session_id="real-api-test-upload")

        assert result["session_id"] == "real-api-test-upload"
        assert result["filename"] == "contract_hardware_warranty.txt"
        assert "html" in result and isinstance(result["html"], str)
        assert "Extended Warranty" in result["html"]
        assert result["chunks_count"] > 0
        assert result["document_id"]
    finally:
        client.close()


def test_real_sync_chat_returns_expected_shape() -> None:
    client = SuperDocsClient(api_key=_api_key)
    try:
        fixture_path = os.path.join(FIXTURES_DIR, "contract_hardware_warranty.txt")
        client.upload_document(fixture_path, session_id="real-api-test-chat")

        result = client.chat(
            "What is the total purchase price stated in this document? "
            "Answer with just the dollar figure.",
            session_id="real-api-test-chat",
        )

        assert result["session_id"] == "real-api-test-chat"
        assert isinstance(result["response"], str) and result["response"]
        assert "document_changes" in result
        assert "usage" in result
        assert result["usage"]["was_billable"] is True
    finally:
        client.close()


def test_real_cancel_job_on_a_genuinely_running_job() -> None:
    """The actual gap this closes: cancel_job() had only ever been hit
    once, by accident, against a job that had already completed (a real
    400 "Job cannot be cancelled" -- confirms the error path, not the
    success path). This test uses a deliberately slow request (a long
    essay-generation prompt) to reliably catch the job while it's still
    pending/in_progress, then cancels it for real and confirms the status
    genuinely transitions to "cancelled" on the next poll."""
    client = SuperDocsClient(api_key=_api_key)
    try:
        job = client.chat_async(
            message=(
                "Write a very long, detailed 3000-word essay about the "
                "history of paper manufacturing, covering ancient China, "
                "the medieval Islamic world, and the European industrial "
                "revolution in extensive detail."
            ),
            session_id="real-api-test-cancel",
            document_html="<p>placeholder</p>",
        )
        job_id = job["job_id"]
        assert job_id

        status_before_cancel = client.get_job(job_id)["status"]
        assert status_before_cancel in ("pending", "in_progress"), (
            f"job reached a terminal status ({status_before_cancel!r}) before "
            "cancel could be tested -- the essay prompt needs to be slower, "
            "or SuperDocs got faster; not a real bug, just a flaky probe"
        )

        cancel_result = client.cancel_job(job_id)
        assert cancel_result["job_id"] == job_id

        final_status = client.get_job(job_id)["status"]
        assert final_status == "cancelled"
    finally:
        client.close()
