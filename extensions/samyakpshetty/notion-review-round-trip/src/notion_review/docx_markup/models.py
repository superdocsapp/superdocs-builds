"""What we extract from a reviewer's marked-up Word file."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DocxComment:
    """A Word comment: an instruction from a reviewer, not a concrete text change."""

    comment_id: str
    author: str
    text: str
    date: str = ""


@dataclass
class ParagraphMarkup:
    """One paragraph, reconstructed both as it was sent and as the reviewer wants it.

    ``original_text`` is the paragraph with insertions removed and deletions restored — i.e.
    exactly what we sent, so it can be matched back to a Notion block. ``proposed_text`` is the
    accept-all result: insertions kept, deletions dropped.
    """

    index: int
    original_text: str
    proposed_text: str
    authors: list[str] = field(default_factory=list)
    comments: list[DocxComment] = field(default_factory=list)

    @property
    def is_text_change(self) -> bool:
        return self.original_text != self.proposed_text

    @property
    def changed(self) -> bool:
        return self.is_text_change or bool(self.comments)


@dataclass
class DocxMarkup:
    """The parsed markup of a whole document."""

    paragraphs: list[ParagraphMarkup]

    def changes(self) -> list[ParagraphMarkup]:
        """Only the paragraphs a reviewer actually touched."""
        return [p for p in self.paragraphs if p.changed]

    def reviewers(self) -> list[str]:
        """Distinct reviewer names across all changes, in first-seen order."""
        seen: dict[str, None] = {}
        for para in self.changes():
            for author in para.authors:
                seen.setdefault(author, None)
            for comment in para.comments:
                if comment.author:
                    seen.setdefault(comment.author, None)
        return list(seen)
