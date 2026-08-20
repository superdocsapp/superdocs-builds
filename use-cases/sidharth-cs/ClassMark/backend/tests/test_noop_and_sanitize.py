"""Regression tests for no-op change classification and for the hard rule
that suggested text is passed through VERBATIM — no heuristic string
surgery ever mutates a proposed replacement."""

import asyncio

from app.superdocs.schemas import PendingChange as WirePendingChange
from app.workflow.models import WorkflowState
from app.workflow.orchestrator import is_noop_change, normalize_for_compare
from tests.fakes import FakeSuperDocsClient
from tests.test_orchestrator import _workflow


# ---- pure classification ---------------------------------------------------

def test_normalize_ignores_tags_line_endings_and_whitespace():
    assert normalize_for_compare("<p>A  B</p>") == "A B"
    assert normalize_for_compare("<p>\r\nA\r\nB</p>") == "A B"
    assert normalize_for_compare('  <p>A</p>  ') == "A"


def test_normalize_is_case_sensitive():
    # A case-only edit is a meaningful change — must NOT be folded away.
    assert normalize_for_compare("<p>Thier</p>") != normalize_for_compare("<p>Their</p>")


def test_is_noop_change_identical_text():
    assert is_noop_change("<p>Same words</p>", "<p>Same words</p>") is True
    assert is_noop_change("<p>Same  words</p>", "<p>Same words</p>") is True  # whitespace only
    assert is_noop_change("<h1>The Role of Renewable Energy</h1>", "<h1>The Role of Renewable Energy</h1>") is True


def test_is_noop_change_real_edits_are_actionable():
    assert is_noop_change("<p>Thier</p>", "<p>There</p>") is False
    assert is_noop_change("<p>structures, this</p>", "<p>structures. This</p>") is False
    assert is_noop_change("<p>cleen</p>", "<p>clean</p>") is False
    assert is_noop_change("<p>a, b</p>", "<p>a; b</p>") is False  # punctuation edit


def test_is_noop_change_missing_text_is_not_noop():
    assert is_noop_change(None, "<p>x</p>") is False
    assert is_noop_change("", "") is False


# ---- verbatim pass-through (no string surgery) ------------------------------

def test_suggested_text_passes_through_verbatim():
    """The suggested replacement is SuperDocs' authoritative text. It must
    reach the workflow byte-for-byte — no regex cleanup, no annotation
    stripping, no reconstruction. Even text that LOOKS like an annotation
    must not be mutated (it may be genuine content or the engine's own
    output; our layer must never decide).

    Documented external behavior: live testing (2026-08) showed the OLD
    instruction wording induced SuperDocs to append 'Changes made:
    Original: ... -> Corrected: ...' inside new_html. The current
    instruction forbids it (3 fresh real runs: zero annotations). If the
    engine ever emits such text again, it passes through verbatim — the
    parser never infers the intended text."""
    fake = FakeSuperDocsClient(
        approve_succeeds=True,
        pending_changes=[
            WirePendingChange(
                chunk_id="c1", change_id="chg1",
                old_html="<p>Thier is a problem.</p>",
                new_html=(
                    "<p>There is a problem. "
                    "Original: Thier -> Corrected: There is a problem.</p>"
                ),
            ),
        ],
    )
    wf = _workflow(fake_superdocs=fake)
    asyncio.run(wf.retrieve_submission())
    asyncio.run(wf.upload_to_superdocs())
    data = asyncio.run(wf.start_review("Review."))
    assert data.state == WorkflowState.AWAITING_APPROVAL
    change = data.pending_changes[0]
    assert change.new_html == (
        "<p>There is a problem. "
        "Original: Thier -> Corrected: There is a problem.</p>"
    )
    # Classification unaffected: this is a REAL change (text differs).
    assert change.is_noop is False


def test_suggested_text_not_reconstructed_from_explanation():
    fake = FakeSuperDocsClient(
        approve_succeeds=True,
        pending_changes=[
            WirePendingChange(
                chunk_id="c6", change_id="chg6",
                old_html="<p>The future is cleen.</p>",
                new_html="<p>The future is clean.</p>",
                ai_explanation="Corrected the misspelling 'cleen' to 'clean'.",
            ),
        ],
    )
    wf = _workflow(fake_superdocs=fake)
    asyncio.run(wf.retrieve_submission())
    asyncio.run(wf.upload_to_superdocs())
    data = asyncio.run(wf.start_review("Review."))
    change = data.pending_changes[0]
    assert change.new_html == "<p>The future is clean.</p>"
    assert change.ai_explanation == "Corrected the misspelling 'cleen' to 'clean'."
    # Explanation and suggested text are separate fields.
    assert "Corrected" not in change.new_html


# ---- workflow integration ---------------------------------------------------

def test_workflow_classifies_noop_and_excludes_from_decisions():
    """A pending change with identical old/new text is marked no-op; it
    needs no decision and is not sent to the approval endpoint."""
    fake = FakeSuperDocsClient(
        approve_succeeds=True,
        pending_changes=[
            WirePendingChange(
                chunk_id="n1", change_id="chgN",
                old_html="<h1>The Role of Renewable Energy in Modern Cities</h1>",
                new_html="<h1>The Role of Renewable Energy in Modern Cities</h1>",
            ),
            WirePendingChange(
                chunk_id="c1", change_id="chg1",
                old_html="<p>Thier report</p>",
                new_html="<p>Their report</p>",
            ),
        ],
    )
    wf = _workflow(fake_superdocs=fake)
    asyncio.run(wf.retrieve_submission())
    asyncio.run(wf.upload_to_superdocs())
    data = asyncio.run(wf.start_review("Review for grammar."))
    assert data.state == WorkflowState.AWAITING_APPROVAL

    noops = [c for c in data.pending_changes if c.is_noop]
    actionable = [c for c in data.pending_changes if not c.is_noop]
    assert len(noops) == 1 and noops[0].chunk_id == "n1"
    assert len(actionable) == 1

    assert data.all_decided() is False  # c1 undecided
    data = asyncio.run(wf.decide("c1", "approved"))
    assert data.all_decided() is True  # no-op excluded from the requirement

    data = asyncio.run(wf.submit_approval())
    assert data.state == WorkflowState.APPROVAL_COMPLETE
    call = fake.approve_batch_calls[0]
    assert call["changes"] == [{"change_id": "chg1", "approved": True}]
    assert all("chgN" not in c["change_id"] for c in call["changes"])


def test_decide_rejects_noop_change():
    fake = FakeSuperDocsClient(
        approve_succeeds=True,
        pending_changes=[
            WirePendingChange(
                chunk_id="n1", change_id="chgN",
                old_html="<p>Same</p>", new_html="<p>Same</p>",
            ),
            WirePendingChange(
                chunk_id="c1", change_id="chg1",
                old_html="<p>A</p>", new_html="<p>B</p>",
            ),
        ],
    )
    wf = _workflow(fake_superdocs=fake)
    asyncio.run(wf.retrieve_submission())
    asyncio.run(wf.upload_to_superdocs())
    asyncio.run(wf.start_review("Review."))
    data = asyncio.run(wf.decide("n1", "approved"))
    assert data.state == WorkflowState.ERROR
    assert "no-op" in data.error


def test_all_noop_review_is_honest_dead_end():
    fake = FakeSuperDocsClient(
        approve_succeeds=True,
        pending_changes=[
            WirePendingChange(
                chunk_id="n1", change_id="chgN",
                old_html="<p>Same text</p>", new_html="<p>Same text</p>",
            ),
        ],
    )
    wf = _workflow(fake_superdocs=fake)
    asyncio.run(wf.retrieve_submission())
    asyncio.run(wf.upload_to_superdocs())
    data = asyncio.run(wf.start_review("Review."))
    assert data.state == WorkflowState.REVIEW_GENERATED
    assert "no-op" in data.timeline[-1].detail
    data = asyncio.run(wf.export_reviewed())
    assert data.state != WorkflowState.EXPORTED
