"""Pure Notion-model helpers: rich-text splitting to stay under Notion's per-object limit."""

from __future__ import annotations

from notion_review.notion.models import (
    Annotations,
    RichText,
    plain_text,
    splice_plain_edit,
    split_rich_text,
)


def test_split_rich_text_respects_the_limit_and_preserves_style_and_link() -> None:
    long = "x" * 4500
    runs = [RichText(text=long, annotations=Annotations(bold=True), href="https://example.com")]

    out = split_rich_text(runs, limit=2000)

    assert [len(r.text) for r in out] == [2000, 2000, 500]
    assert "".join(r.text for r in out) == long  # nothing lost or reordered
    assert all(r.annotations.bold and r.href == "https://example.com" for r in out)


def test_split_rich_text_leaves_short_runs_untouched() -> None:
    runs = plain_text("short enough")
    assert split_rich_text(runs) == runs


def _styled() -> list[RichText]:
    # "Ships in Q3, " + bold "on time" + ", per the plan."
    return [
        RichText(text="Ships in Q3, "),
        RichText(text="on time", annotations=Annotations(bold=True)),
        RichText(text=", per the plan."),
    ]


def test_splice_changes_only_the_differing_span_and_keeps_styling() -> None:
    runs = _styled()
    out = splice_plain_edit(runs, "Ships in Q4, on time, per the plan.")

    assert "".join(r.text for r in out) == "Ships in Q4, on time, per the plan."
    bold = [r for r in out if r.annotations.bold]
    assert len(bold) == 1 and bold[0].text == "on time"  # the bold run is untouched


def test_splice_preserves_a_link_outside_the_changed_span() -> None:
    runs = [
        RichText(text="See "),
        RichText(text="the doc", href="https://example.com/v1"),
        RichText(text=" now."),
    ]
    out = splice_plain_edit(runs, "See the doc later.")

    assert "".join(r.text for r in out) == "See the doc later."
    linked = [r for r in out if r.href == "https://example.com/v1"]
    assert linked and linked[0].text == "the doc"


def test_splice_on_unstyled_text_is_a_plain_rewrite() -> None:
    out = splice_plain_edit(plain_text("the quick brown fox"), "the quick red fox")
    assert "".join(r.text for r in out) == "the quick red fox"
    assert all(r.annotations == Annotations() and r.href is None for r in out)
