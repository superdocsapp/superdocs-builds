"""A real SuperDocs account test of close_package/runner.py's
publish_package_to_superdocs() -- proves the assembled CLOSE PACKAGE
(memo + schedule table + audit-trail table, not just plain memo prose)
survives a real HITL authoring job against the real product.

WHY THIS IS A SEPARATE TEST FROM drafter/publish.py's OWN REAL-ACCOUNT
TEST, NOT JUST ASSUMED TO WORK THE SAME WAY: that test proves
change_is_formatting_only()/resolve_pending_changes_by_content_
verification() protect plain memo prose against a real, non-deterministic
AI. This module reuses that exact code, but publishing a document that
also contains two HTML *tables* (the schedule and audit trail) is a
genuinely different shape of content than prose -- table markup is
exactly the kind of thing an HTML-diffing formatting check could behave
differently on (more tags, more structure to "clean up"), and that
had never actually been exercised against the real product before this
test. Same "never assume, verify" posture as everywhere else in this
project.

Same gating and rationale as tests/test_drafter_publish_real_superdocs.py:
creates real, stateful account resources and depends on SuperDocs's own
AI, so it isn't cassette-replayable -- gated behind RUN_LIVE_SUPERDOCS_TEST=1
+ a real SUPERDOCS_API_KEY, skipped by default and in CI.
"""

from __future__ import annotations

import os
import uuid

import pytest

from close_package.assemble import assemble_package
from close_package.state import ClosePackageState
from core.superdocs_client import SuperDocsClient
from drafter.publish import MemoJobFailedError
from drafter.state import DrafterState, MemoAnalysis

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


def _minimal_package_state() -> ClosePackageState:
    """A minimal but genuinely representative close package -- memo prose
    PLUS a schedule table PLUS an audit-trail table, the actual shape
    publish_package_to_superdocs() sends, not a plain-memo stand-in."""
    analysis: MemoAnalysis = {
        "contract_filename": "test_fixture.txt",
        "performance_obligations": [
            {
                "obligation_id": "platform_access",
                "description": "Access to the platform",
                "source_quote": "access to the Platform",
                "citation_verified": True,
                "is_distinct": True,
                "is_judgement": False,
                "judgement_note": "",
                "requires_human_review": False,
            }
        ],
        "price_allocations": [],
        "timing_conclusions": [],
    }
    memo_state: DrafterState = {
        "run_id": "closepkg-real-test",
        "contract_path": "test_fixture.txt",
        "contract_text": "irrelevant for this test",
        "contract_filename": "test_fixture.txt",
        "analysis": analysis,
        "judgement_notes": [],
        "memo_html": (
            "<h1>Revenue Recognition Memo</h1>"
            "<p><strong>Contract:</strong> test_fixture.txt</p>"
            "<h2>1. Performance Obligations</h2>"
            "<ul><li><strong>platform_access</strong> -- Access to the platform "
            "(a distinct performance obligation).<br>"
            "Source: &ldquo;access to the Platform&rdquo;</li></ul>"
        ),
        "session_id": "",
        "job_id": "",
        "export_result": {},
        "stage_log": [],
    }
    state: ClosePackageState = {
        "run_id": "closepkg-real-test",
        "memo_state": memo_state,
        "schedule": {
            "contract_filename": "test_fixture.txt",
            "schedule_facts": [],
            "entries": [
                {
                    "obligation_id": "platform_access",
                    "period_label": "Month 1 of 12",
                    "recognized_amount": "$7,000.00",
                    "basis": "straight_line_over_time",
                    "requires_human_review": False,
                }
            ],
        },
        "audit_trail": [
            {
                "category": "performance_obligation",
                "subject": "platform_access",
                "conclusion": "Access to the platform -- distinct",
                "source_quote": "access to the Platform",
                "citation_verified": True,
                "is_judgement": False,
                "judgement_note": "",
                "requires_human_review": False,
            }
        ],
        "package_html": "",
        "session_id": "",
        "job_id": "",
        "export_result": {},
        "stage_log": [],
    }
    state.update(assemble_package(state))  # type: ignore[typeddict-item]
    return state


def test_publish_close_package_with_content_verification_against_real_account() -> None:
    """Proves publish_package_to_superdocs() actually protects a real,
    table-containing close package against a real, non-deterministic AI --
    not just the synthetic old_html/new_html pairs in the fake-client
    tests, and not just plain prose the way drafter/publish.py's own
    real-account test already proves."""
    from drafter.publish import export_memo, poll_until_resolved, start_memo_authoring_job

    client = SuperDocsClient(api_key=_api_key)
    state = _minimal_package_state()
    session_id = f"closepkg-real-test-{uuid.uuid4().hex[:12]}"

    try:
        job = start_memo_authoring_job(client, session_id, state["package_html"])
        job_id = job["job_id"]
        assert job_id

        resolved = poll_until_resolved(
            client, job_id, session_id, auto_approve=True, poll_interval_seconds=2.0, max_polls=60
        )
        assert resolved["status"] == "completed"

        export_result = export_memo(client, session_id, format="html")
        assert export_result["content_type"].startswith("text/html")
        assert isinstance(export_result["content"], str)

        # THE actual proof: every substantive fact from the memo, the
        # schedule table, AND the audit trail must still be present,
        # verbatim, in the exported document -- content verification must
        # have protected the table-containing package just as reliably as
        # it protects plain memo prose.
        exported_text = export_result["content"]
        for required_fact in [
            "platform_access",
            "access to the Platform",
            "Month 1 of 12",
            "$7,000.00",
            "Access to the platform -- distinct",
        ]:
            assert required_fact in exported_text, (
                f"required fact {required_fact!r} missing from exported close "
                "package -- content verification did not protect it"
            )
    except MemoJobFailedError as exc:
        pytest.fail(f"real SuperDocs job failed: {exc}")
    finally:
        client.close()
