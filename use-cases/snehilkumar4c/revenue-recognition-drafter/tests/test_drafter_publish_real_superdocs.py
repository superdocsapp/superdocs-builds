"""A real SuperDocs account test of drafter/publish.py -- this project's
first genuine exercise of the SuperDocs integration itself, not a mock.

WHY THIS ISN'T A VCR-CASSETTE TEST LIKE THE REAL-MODEL LLM TESTS: those
replay a deterministic request/response pair forever with no live access
needed afterward. This flow doesn't fit that shape -- it creates real,
stateful account resources (a session, a job) and its outcome depends on
what SuperDocs's own AI actually does with a given input, which is not
guaranteed identical between runs the way a cached LLM response is. So
this test is gated behind an explicit opt-in flag (RUN_LIVE_SUPERDOCS_TEST=1)
and a real SUPERDOCS_API_KEY, and is skipped by default -- including in CI,
which has neither. Run manually when validating the real integration path.

Reproduces, through our ACTUAL CODE (not manual MCP calls), the exact
finding from the 2026-08-11 MCP validation session that led to
drafter/publish.py's change_is_formatting_only() fix: SuperDocs's AI does
not reliably honor a plain-English "don't alter wording" instruction, so
auto_approve=True must verify each proposed change in code rather than
trust it.
"""

from __future__ import annotations

import os
import uuid

import pytest

from core.superdocs_client import SuperDocsClient
from drafter.publish import (
    MemoJobFailedError,
    export_memo,
    poll_until_resolved,
    start_memo_authoring_job,
)

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


def test_publish_memo_with_content_verification_against_real_account() -> None:
    """A minimal memo with one line that, per the 2026-08-11 finding, is
    exactly the kind of text SuperDocs's AI has been observed rewording
    even when told not to (the word "recognition" near a formatting
    instruction). Proves resolve_pending_changes_by_content_verification()
    actually protects real content against a real, non-deterministic AI,
    not just the synthetic old_html/new_html pairs in the fake-client
    tests."""
    client = SuperDocsClient(api_key=_api_key)
    session_id = f"revrec-real-test-{uuid.uuid4().hex[:12]}"
    memo_html = (
        "<h1>Revenue Recognition Memo</h1>"
        "<p><strong>Contract:</strong> test_fixture.txt</p>"
        "<h2>1. Performance Obligations</h2>"
        "<ul><li><strong>platform_access</strong> -- Access to the platform "
        "(a distinct performance obligation).<br>"
        "Source: &ldquo;access to the Platform&rdquo;</li></ul>"
        "<h2>3. Timing of Revenue Recognition</h2>"
        "<ul><li><strong>platform_access</strong>: revenue is recognized "
        "over time -- customer benefits continuously throughout the term."
        "<br>Source: &ldquo;twelve (12) months&rdquo;</li></ul>"
    )

    try:
        job = start_memo_authoring_job(client, session_id, memo_html)
        job_id = job["job_id"]
        assert job_id

        resolved = poll_until_resolved(
            client, job_id, session_id, auto_approve=True, poll_interval_seconds=2.0, max_polls=60
        )
        assert resolved["status"] == "completed"

        export_result = export_memo(client, session_id, format="html")
        assert export_result["content_type"].startswith("text/html")
        assert isinstance(export_result["content"], str)

        # THE actual proof: whatever came back from SuperDocs, every
        # substantive fact from the original memo must still be present,
        # verbatim, in the exported document -- content-verification must
        # have actually protected it from any AI-side rewording, exactly
        # the property the 2026-08-11 finding showed could NOT be trusted
        # to prompt instructions alone.
        exported_text = export_result["content"]
        for required_fact in ["platform_access", "twelve (12) months", "access to the Platform"]:
            assert required_fact in exported_text, (
                f"required fact {required_fact!r} missing from exported document -- "
                "content verification did not protect it"
            )
    except MemoJobFailedError as exc:
        pytest.fail(f"real SuperDocs job failed: {exc}")
    finally:
        client.close()
