"""A success line must mean the document is in the state the step claimed.

A turn that proposes nothing is ambiguous: the document may already satisfy the
instruction, or the model may have missed it. Reporting both as success is a bluff, and a
live run produced exactly the second case — a document plainly containing "PagerDuty"
came back with no proposed changes and the step was recorded as done.

The check is a plain string test against the document the server holds. It costs nothing,
and its value is precisely that it cannot be talked out of what it sees.
"""

from __future__ import annotations

import sqlite3

from longhaul.model import (
    UNCHECKED,
    UNMET_BY_CHOICE,
    UNMET_NO_CHANGES,
    UNMET_UNKNOWN,
    VERIFIED,
)
from longhaul.planner import derive_expectations
from longhaul.verify import check, is_alarming

from .conftest import Harness

EXPECT = '{"absent": ["PagerDuty"], "present": []}'


def test_expectations_are_derived_from_the_instruction_itself() -> None:
    """The instruction already states what should be true afterwards. Making the author
    repeat it in a second place is how the two drift apart."""
    assert derive_expectations('replace "PagerDuty" with "Rootly"', None) == EXPECT
    # Only the negative half: a document that never said PagerDuty should not be expected
    # to gain Rootly, and asserting it would fail every document correctly left alone.
    assert '"present": []' in derive_expectations('replace "A" with "B"', None)
    assert derive_expectations("Remove the section titled \"X\".", None) is None


def test_an_explicit_verify_block_wins() -> None:
    assert derive_expectations(
        "anything at all", {"absent": ["Foo"], "present": ["Bar"]}
    ) == '{"absent": ["Foo"], "present": ["Bar"]}'


def test_the_silent_miss_is_caught() -> None:
    """Nothing proposed, and the document still says the thing. This is the live bug."""
    verification, detail = check(
        "<p>Page via PagerDuty.</p>", EXPECT, proposed=0, rejected=0
    )
    assert verification == UNMET_NO_CHANGES
    assert is_alarming(verification)
    assert "PagerDuty" in detail


def test_a_rejection_is_a_decision_not_a_defect() -> None:
    verification, detail = check(
        "<p>Page via PagerDuty.</p>", EXPECT, proposed=2, rejected=2
    )
    assert verification == UNMET_BY_CHOICE
    assert not is_alarming(verification)
    assert "rejected" in detail


def test_recovery_without_the_record_says_so_rather_than_guessing() -> None:
    verification, detail = check(
        "<p>Page via PagerDuty.</p>", EXPECT, proposed=0, rejected=0, recovered=True
    )
    assert verification == UNMET_UNKNOWN
    assert not is_alarming(verification)
    assert "recovery" in detail


def test_matches_inside_markup_do_not_count() -> None:
    """A chunk id that happens to contain the word is not the document saying it."""
    verification, _ = check(
        '<p data-chunk-id="PagerDuty-1">All good.</p>', EXPECT, proposed=1, rejected=0
    )
    assert verification == VERIFIED


def test_a_step_with_nothing_to_assert_is_unchecked_not_verified() -> None:
    verification, detail = check("<p>anything</p>", None, proposed=0, rejected=0)
    assert verification == UNCHECKED
    assert detail is None


def test_a_clean_run_verifies_its_steps(harness: Harness) -> None:
    harness.reset()
    assert harness.run().returncode == 0
    report = harness.report()

    assert report["totals"]["verified"] > 0
    assert report["totals"]["unmet_expectations"] == 0
    for step in report["steps"]:
        assert step["verification"] != UNMET_NO_CHANGES


def test_a_run_whose_document_does_not_match_does_not_report_completed(
    harness: Harness,
) -> None:
    """The failure the live API produced, forced deterministically.

    The step is marked done in the ledger with an expectation it never met and nothing
    proposed — exactly the shape of a model that quietly skipped the work.
    """
    harness.reset()
    assert harness.run().returncode == 0

    db = harness.state_dir / "longhaul.db"
    conn = sqlite3.connect(str(db))
    try:
        # Put step 2 back to be re-finished, with an expectation the document cannot meet.
        conn.execute(
            "UPDATE steps SET state='committed', verification=NULL, "
            "verification_detail=NULL, verify_json=? WHERE run_id=? AND step_index=2",
            ('{"absent": ["Status Page"], "present": []}', harness.run_id),
        )
        conn.execute(
            "DELETE FROM proposals WHERE run_id=? AND step_index=2", (harness.run_id,)
        )
        conn.execute(
            "DELETE FROM decisions WHERE run_id=? AND step_index=2", (harness.run_id,)
        )
        conn.commit()
    finally:
        conn.close()

    result = harness.run()
    assert result.returncode == 4, "a step that did not do its job must not exit success"

    report = harness.report()
    assert report["status"] == "blocked"
    assert report["totals"]["unmet_expectations"] == 1
    unmet = [s for s in report["steps"] if s["verification"] == UNMET_NO_CHANGES]
    assert len(unmet) == 1 and unmet[0]["step_index"] == 2
    assert "Status Page" in unmet[0]["verification_detail"]
    assert "did not do what they said" in result.stdout
