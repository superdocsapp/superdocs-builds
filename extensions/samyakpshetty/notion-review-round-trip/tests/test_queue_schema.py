"""A change has to be readable at a glance, or the queue is useless for deciding."""

from __future__ import annotations

from notion_review.domain import ChangeOperation, ChangeSource, ProposedChange
from notion_review.notion.queue_schema import changed_span, row_properties, summarize

SENTENCE = (
    "Northwind Analytics launches to general availability in Q3 and is aimed at {} "
    "who currently run their reporting out of spreadsheets."
)


def test_only_the_differing_words_are_shown() -> None:
    before = SENTENCE.format("operations teams")
    after = SENTENCE.format("revenue operations teams")

    assert changed_span(before, after) == ("", "revenue ")
    # The long shared sentence is trimmed away, so the change reads at a glance.
    assert summarize(before, after) == "add “revenue”"


def test_a_deletion_reads_as_a_deletion() -> None:
    assert summarize("ship it quickly today", "ship it today") == "remove “quickly”"


def test_a_replaced_phrase_reads_as_before_and_after() -> None:
    assert summarize("the trial lasts fourteen days", "the trial lasts thirty days") == (
        "“fourteen” → “thirty”"
    )


def test_a_wholesale_rewrite_is_clipped_not_dumped() -> None:
    before = "The Snowflake connector has not been load tested and it is kind of a question mark."
    after = "Load testing of the Snowflake connector is outstanding and tracked as a launch risk."

    summary = summarize(before, after)

    assert len(summary) < 110  # never a wall of text
    assert "…" in summary  # and it says so when it clipped


def test_identical_text_does_not_pretend_to_be_a_change() -> None:
    assert changed_span("same", "same") == ("", "")


def test_a_row_title_is_the_change_not_the_whole_sentence() -> None:
    before = SENTENCE.format("operations teams")
    after = SENTENCE.format("revenue operations teams")
    proposal = ProposedChange(
        chunk_id="c1",
        notion_block_id="b1",
        operation=ChangeOperation.REPLACE,
        source=ChangeSource.TRACKED_CHANGE,
        reviewer_name="Dana Reviewer",
    )

    props = row_properties(proposal, before=before, after=after)
    title = props["Change"]["title"][0]["text"]["content"]

    assert len(title) < 60  # the old behaviour was ~120 characters of duplicated sentence
    assert "revenue" in title
    # The full text is still on the row, in the Before/After fields.
    assert props["Before"]["rich_text"][0]["text"]["content"] == before
    assert props["After"]["rich_text"][0]["text"]["content"] == after
