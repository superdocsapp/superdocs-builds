"""Invariants of the domain vocabulary.

These run with no key, no network and no fixture files, so they stay fast enough
to run on every save.
"""

from __future__ import annotations

import dataclasses

import pytest

from thread_resolver.domain.models import (
    Anchor,
    Classification,
    Comment,
    Decision,
    Disposition,
    ProposedEdit,
    ReviewItem,
    Thread,
)


def make_comment(comment_id: str = "1", author: str = "Ada", text: str = "tighten this") -> Comment:
    return Comment(comment_id=comment_id, para_id=f"p{comment_id}", author=author, text=text)


def make_thread(*, replies: tuple[Comment, ...] = (), resolved: bool = False) -> Thread:
    return Thread(
        root=make_comment(),
        replies=replies,
        anchor=Anchor(text="The vendor shall deliver within 30 days.", paragraph_index=4),
        resolved=resolved,
    )


class TestComment:
    def test_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="comment_id is required"):
            Comment(comment_id="", para_id=None, author="Ada", text="hi")

    def test_is_immutable(self) -> None:
        comment = make_comment()
        with pytest.raises(dataclasses.FrozenInstanceError):
            comment.text = "changed"  # type: ignore[misc]


class TestThread:
    def test_comments_are_root_then_replies_in_order(self) -> None:
        first = make_comment("2", "Grace", "agreed")
        second = make_comment("3", "Alan", "not so fast")
        thread = make_thread(replies=(first, second))

        assert [c.comment_id for c in thread.comments] == ["1", "2", "3"]

    def test_participants_collects_every_author(self) -> None:
        thread = make_thread(replies=(make_comment("2", "Grace"), make_comment("3", "Ada")))

        assert thread.participants == frozenset({"Ada", "Grace"})

    def test_resolved_thread_is_not_open(self) -> None:
        assert make_thread(resolved=True).is_open is False
        assert make_thread().is_open is True

    def test_transcript_attributes_each_line_to_its_author(self) -> None:
        thread = make_thread(replies=(make_comment("2", "Grace", "keep it"),))

        assert thread.transcript() == "Ada: tighten this\nGrace: keep it"


class TestContentHash:
    """Identity used to avoid paying twice for the same thread."""

    def test_is_stable_across_equal_threads(self) -> None:
        assert make_thread().content_hash() == make_thread().content_hash()

    def test_changes_when_a_reply_is_added(self) -> None:
        before = make_thread()
        after = make_thread(replies=(make_comment("2", "Grace", "keep it"),))

        assert before.content_hash() != after.content_hash()

    def test_changes_when_the_anchored_passage_changes(self) -> None:
        base = make_thread()
        moved = Thread(
            root=base.root,
            replies=base.replies,
            anchor=Anchor(text="Different passage entirely.", paragraph_index=4),
        )

        assert base.content_hash() != moved.content_hash()

    def test_is_not_confused_by_field_boundaries(self) -> None:
        """Concatenating fields without a separator would collide on these two."""
        left = Thread(root=Comment(comment_id="1", para_id=None, author="ab", text="c"))
        right = Thread(root=Comment(comment_id="1", para_id=None, author="a", text="bc"))

        assert left.content_hash() != right.content_hash()


class TestClassification:
    """An instruction may exist only where an edit is permitted."""

    def test_actionable_requires_an_instruction(self) -> None:
        with pytest.raises(ValueError, match="must carry an instruction"):
            Classification(
                disposition=Disposition.ACTIONABLE,
                reason="single clear request",
                decided_by="rule:single-comment",
            )

    @pytest.mark.parametrize(
        "disposition",
        [
            Disposition.CONTESTED,
            Disposition.QUESTION,
            Disposition.UNANCHORED,
            Disposition.QUARANTINED,
        ],
    )
    def test_non_actionable_cannot_carry_an_instruction(self, disposition: Disposition) -> None:
        with pytest.raises(ValueError, match="must not carry an instruction"):
            Classification(
                disposition=disposition,
                reason="whatever the reason",
                decided_by="rule:test",
                instruction="rewrite the clause",
            )

    def test_actionable_with_an_instruction_is_accepted(self) -> None:
        classification = Classification(
            disposition=Disposition.ACTIONABLE,
            reason="single clear request",
            decided_by="rule:single-comment",
            instruction="shorten the delivery clause",
        )

        assert classification.instruction == "shorten the delivery clause"


class TestReviewItem:
    """Only an approved edit closes a thread."""

    def _item(
        self,
        *,
        disposition: Disposition = Disposition.ACTIONABLE,
        with_edit: bool = True,
    ) -> ReviewItem:
        classification = Classification(
            disposition=disposition,
            reason="reason",
            decided_by="rule:test",
            instruction="shorten the clause" if disposition is Disposition.ACTIONABLE else None,
        )
        edits = (
            (
                ProposedEdit(
                    change_id="ch_1",
                    chunk_id="c_4",
                    operation="edit",
                    old_html="<p>before</p>",
                    new_html="<p>after</p>",
                    explanation="shortened",
                ),
            )
            if with_edit
            else ()
        )
        return ReviewItem(thread=make_thread(), classification=classification, proposed_edits=edits)

    def test_approved_edit_closes_the_thread(self) -> None:
        item = self._item().with_decision(Decision.APPROVE)

        assert item.closes_thread is True

    def test_rejected_edit_leaves_the_thread_open(self) -> None:
        item = self._item().with_decision(Decision.REJECT)

        assert item.closes_thread is False

    def test_approving_a_finding_without_an_edit_leaves_the_thread_open(self) -> None:
        item = self._item(disposition=Disposition.CONTESTED, with_edit=False)

        assert item.with_decision(Decision.APPROVE).closes_thread is False

    def test_undecided_item_closes_nothing(self) -> None:
        assert self._item().closes_thread is False

    def test_with_decision_does_not_mutate_the_original(self) -> None:
        original = self._item()
        decided = original.with_decision(Decision.APPROVE)

        assert original.decision is None
        assert decided.decision is Decision.APPROVE

    def test_noop_edit_is_detected(self) -> None:
        edit = ProposedEdit(
            change_id="ch_1",
            chunk_id=None,
            operation="edit",
            old_html="<p>same</p>",
            new_html="<p>same</p>",
            explanation="no change",
        )

        assert edit.is_noop is True
