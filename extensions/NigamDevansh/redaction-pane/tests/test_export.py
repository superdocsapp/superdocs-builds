"""8C — the clean copy, and the approval gate in front of it.

Driven against the recorded redaction round: `11_redaction_changes.json` is
seven real `edit` operations SuperDocs proposed, header and footer included, and
`14_hidden_redacted.docx` is the exported result. No key, no network.

**The tests that matter are the rejections.** Approving what a model proposes is
the easy half; refusing a change that redacts more than the reviewer confirmed
is the half that makes "nothing is removed without a human click" survive
contact with an AI that edits documents.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from service import export
from service._portable.superdocs_client import PendingChange

# Vendored beside the tests, not read from a repository root. This project
# ships as a standalone pull request, so it may not assume anything exists
# outside its own folder — the same reason `_portable/` holds a copy of the
# shared client rather than importing it.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "superdocs_responses"

RECORDED = json.loads((FIXTURES / "11_redaction_changes.json").read_text())
CHANGES = [
    PendingChange(
        change_id=item["change_id"],
        operation=item["operation"],
        chunk_id=item["chunk_id"],
        old_html=item["old_html"],
        new_html=item["new_html"],
        ai_explanation=item.get("ai_explanation", ""),
        document_id=item.get("document_id", ""),
    )
    for item in RECORDED
]

# Exactly what the recorded round replaced, with the marker it used.
CONFIRMED: dict[str, str] = {
    "Jonathan Michael Whitfield": "[REDACTED]",
    "482 Rosewood Terrace, Suite 1200": "[REDACTED]",
    "Springfield, Illinois 62704": "[REDACTED]",
    "Sarah Chen": "[REDACTED]",
    "77 Harbour Road, Boston MA 02110": "[REDACTED]",
    "4111 1111 1111 1111": "[REDACTED]",
    "jwhitfield@acme-example.com": "[REDACTED]",
    "555-0142": "[REDACTED]",
}


class TestTheApprovalGate:
    def test_every_recorded_change_is_reproducible_and_approved(self) -> None:
        """The premise. If our substitution does not reproduce what SuperDocs
        actually returned, every rejection test below proves nothing."""
        decisions, approved = export.decide(CHANGES, CONFIRMED)

        assert approved == len(CHANGES) == 7
        assert all(decision.approved for decision in decisions)

    def test_a_change_that_removes_more_is_rejected(self) -> None:
        """**The one that matters.** Over-redaction is still a change nobody
        approved, and it is the failure mode of asking a model to edit a
        document: it tidies a sentence while it is in there.
        """
        greedy = PendingChange(
            change_id="x",
            operation="edit",
            chunk_id="c",
            old_html="<p>Fees are due Net 30. Card on file 4111 1111 1111 1111.</p>",
            new_html="<p>[REDACTED]</p>",  # took the whole paragraph
        )

        decisions, approved = export.decide([greedy], CONFIRMED)

        assert approved == 0
        assert decisions[0].approved is False
        assert "more than the confirmed redactions" in (decisions[0].feedback or "")

    def test_a_change_that_rephrases_is_rejected(self) -> None:
        rewritten = PendingChange(
            change_id="x",
            operation="edit",
            chunk_id="c",
            old_html="<p>Fees are due Net 30. Card on file 4111 1111 1111 1111.</p>",
            new_html="<p>Fees are payable within 30 days. Card on file [REDACTED].</p>",
        )

        assert export.decide([rewritten], CONFIRMED)[1] == 0

    def test_a_change_touching_text_nobody_confirmed_is_rejected(self) -> None:
        """A string the reviewer never saw, redacted anyway."""
        extra = PendingChange(
            change_id="x",
            operation="edit",
            chunk_id="c",
            old_html="<p>Contact Sarah Chen or Priya Raman.</p>",
            new_html="<p>Contact [REDACTED] or [REDACTED].</p>",  # Priya was not confirmed
        )

        assert export.decide([extra], CONFIRMED)[1] == 0

    def test_a_rejection_carries_feedback_so_the_ai_can_revise(self) -> None:
        """Rejecting without saying why ends the round with the same proposal."""
        bad = PendingChange(
            change_id="x", operation="edit", chunk_id="c",
            old_html="<p>Sarah Chen</p>", new_html="<p></p>",
        )

        assert export.decide([bad], CONFIRMED)[0][0].feedback


class TestSubstitution:
    def test_a_longer_string_is_replaced_before_a_shorter_one_inside_it(self) -> None:
        """Order is not cosmetic. `Margaret` replaced first leaves
        `[NAME REDACTED] Ellen Hollis` — a redaction that reads as complete and
        is not."""
        items = {"Margaret Ellen Hollis": "[NAME REDACTED]", "Margaret": "[NAME REDACTED]"}

        result = export.expected_text("<p>Margaret Ellen Hollis signed.</p>", items)

        assert result == "[NAME REDACTED] signed."

    def test_entities_and_tags_are_normalised_on_both_sides(self) -> None:
        """SuperDocs re-emits HTML with its own escaping and styling. Comparing
        raw markup would reject a correct change for an attribute we do not
        care about."""
        change = PendingChange(
            change_id="x", operation="edit", chunk_id="c",
            old_html='<p style="a">Acme &amp; Co — Sarah Chen</p>',
            new_html="<p>Acme &amp; Co — [REDACTED]</p>",
        )

        assert export.decide([change], CONFIRMED)[1] == 1

    def test_the_instruction_names_both_halves_of_every_substitution(self) -> None:
        """"Redact the personal data" is not checkable. This is."""
        text = export.instruction({"Sarah Chen": "[NAME REDACTED]"})

        assert "Sarah Chen" in text
        assert "[NAME REDACTED]" in text
        assert "Do not rephrase" in text


class TestVerification:
    def test_the_recorded_clean_export_verifies(self) -> None:
        from service.verify_package import check

        report = check(
            (FIXTURES / "14_hidden_redacted.docx").read_bytes(),
            ["123-45-6789", "4111 1111 1111 1111"],
        )

        assert report.clean is True
        assert report.markers_found > 0

    def test_the_uncleaned_export_does_not(self) -> None:
        """Export alone scrubs nothing. Measured, not assumed."""
        from service.verify_package import check

        report = check(
            (FIXTURES / "13_hidden_export.docx").read_bytes(),
            ["123-45-6789", "4111 1111 1111 1111"],
        )

        assert report.clean is False


class FakeClient:
    """The four calls, in the order `export.run` makes them.

    It hands back the **raw recorded dicts**, not parsed objects, so the real
    `parse_pending_changes` runs — a fake that pre-parsed would skip the shape
    the wire actually uses.
    """

    def __init__(self, changes: list[dict], *, exported: bytes) -> None:
        self.changes = changes
        self.exported = exported
        self.approved: list[Any] = []
        self.rounds = 0

    def upload_document(self, **_: Any) -> Any:
        return type("Upload", (), {"durable_document_id": "durable-123"})()

    def chat_async(self, **kwargs: Any) -> Any:
        self.message = kwargs["message"]
        return type("Handle", (), {"job_id": "job-1"})()

    def wait_for_job(self, _job_id: str, **_: Any) -> Any:
        self.rounds += 1
        status = "awaiting_approval" if self.rounds == 1 else "completed"
        return type(
            "Job", (), {"status": status, "metadata": {"pending_changes": self.changes}}
        )()

    def approve(self, **kwargs: Any) -> Any:
        self.approved.extend(kwargs["changes"])
        return type("Approved", (), {"batch_complete": True})()

    def export(self, **_: Any) -> Any:
        return type(
            "Export", (), {"content": self.exported, "filename": "clean.docx", "warnings": []}
        )()


class TestTheWholeFlow:
    @pytest.fixture
    def clean_bytes(self) -> bytes:
        return (FIXTURES / "14_hidden_redacted.docx").read_bytes()

    def test_it_uploads_instructs_approves_exports_and_verifies(
        self, clean_bytes: bytes
    ) -> None:
        client = FakeClient(RECORDED, exported=clean_bytes)

        result = export.run(
            client=client, session_id="s", filename="a.docx", data=b"PK", items=CONFIRMED
        )

        assert result.clean is True
        assert result.content == clean_bytes
        assert result.approved == len(RECORDED)
        assert result.rejected == 0
        assert all(decision.approved for decision in client.approved)
        # The instruction carried the pairs, not a vague ask.
        assert "Sarah Chen" in client.message

    def test_an_export_that_still_carries_the_text_is_not_reported_clean(self) -> None:
        """The whole point of verifying. `13_hidden_export.docx` is a real
        export that kept an SSN in a tracked deletion and a card in a comment;
        handing that back as a clean copy is the failure this phase exists to
        make impossible."""
        dirty = (FIXTURES / "13_hidden_export.docx").read_bytes()
        client = FakeClient(RECORDED, exported=dirty)

        result = export.run(
            client=client, session_id="s", filename="a.docx", data=b"PK",
            items={**CONFIRMED, "123-45-6789": "[SSN REDACTED]"},
        )

        assert result.clean is False
        assert result.report is not None
        assert result.report.residue

    def test_nothing_confirmed_means_no_call_is_made(self) -> None:
        """A SuperDocs operation costs quota. Spending one to redact nothing is
        a bill for an empty result."""
        client = FakeClient(RECORDED, exported=b"")

        result = export.run(
            client=client, session_id="s", filename="a.docx", data=b"PK", items={}
        )

        assert result.content == b""
        assert client.rounds == 0
        assert "nothing confirmed" in result.warnings[0]

    def test_a_run_that_never_leaves_approval_exports_nothing(self) -> None:
        """Exporting while changes are still unapproved produces a file missing
        the redactions — clean-looking, never cleaned."""

        class NeverDone(FakeClient):
            def wait_for_job(self, _job_id: str, **_: Any) -> Any:
                self.rounds += 1
                return type(
                    "Job", (), {"status": "awaiting_approval", "metadata": {"pending_changes": []}}
                )()

        client = NeverDone(RECORDED, exported=b"never")
        result = export.run(
            client=client, session_id="s", filename="a.docx", data=b"PK",
            items={"Sarah Chen": "[NAME REDACTED]"},
        )

        assert result.content == b""
        assert result.clean is False
        assert "still awaiting approval" in result.warnings[-1]

    def test_clean_is_false_when_nothing_was_produced(self) -> None:
        """`report is None` must not read as success. Defaulting it the other
        way would be the single worst bug in this file."""
        assert export.Result().clean is False
