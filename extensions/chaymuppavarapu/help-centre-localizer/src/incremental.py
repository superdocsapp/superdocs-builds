from dataclasses import dataclass
import hashlib
from difflib import SequenceMatcher


@dataclass
class ParagraphChange:
    index: int
    old_text: str | None
    new_text: str | None
    changed: bool


@dataclass
class IncrementalResult:
    changes: list[ParagraphChange]

    @property
    def changed_indices(self) -> list[int]:
        return [
            change.index
            for change in self.changes
            if change.changed
        ]


@dataclass
class ContentUnit:
    """
    A localizable piece of article content.

    key:
        Stable logical identity such as p:0, h1:0,
        figcaption:0, or img-alt:0.

    kind:
        HTML element type.

    index:
        Occurrence index within that element type.

    text:
        Human-readable source text.
    """

    key: str
    kind: str
    index: int
    text: str


@dataclass
class ContentChange:
    """
    Change between two versions of a localizable
    content unit.
    """

    key: str
    kind: str
    index: int
    old_text: str | None
    new_text: str | None
    changed: bool


@dataclass
class ContentIncrementalResult:
    changes: list[ContentChange]

    @property
    def changed_keys(self) -> list[str]:
        return [
            change.key
            for change in self.changes
            if change.changed
        ]

    @property
    def changed_units(self) -> list[ContentChange]:
        return [
            change
            for change in self.changes
            if change.changed
        ]


class IncrementalAnalyzer:
    """
    Detect changes in localizable article content.

    The original paragraph-level API is preserved.

    The generalized API supports:
        - headings
        - paragraphs
        - figcaptions
        - image alt text
    """

    @staticmethod
    def _hash(text: str) -> str:
        normalized = " ".join(text.split())

        return hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest()

    @classmethod
    def _changed(
        cls,
        old_text: str | None,
        new_text: str | None,
    ) -> bool:
        if old_text is None or new_text is None:
            return True

        return (
            cls._hash(old_text)
            != cls._hash(new_text)
        )

    def compare(
        self,
        old_paragraphs: list[str],
        new_paragraphs: list[str],
    ) -> IncrementalResult:
        """
        Backwards-compatible paragraph comparison.

        Existing paragraph-level callers and tests continue
        to work unchanged.
        """

        max_length = max(
            len(old_paragraphs),
            len(new_paragraphs),
        )

        changes = []

        for index in range(max_length):
            old_text = (
                old_paragraphs[index]
                if index < len(old_paragraphs)
                else None
            )

            new_text = (
                new_paragraphs[index]
                if index < len(new_paragraphs)
                else None
            )

            changes.append(
                ParagraphChange(
                    index=index,
                    old_text=old_text,
                    new_text=new_text,
                    changed=self._changed(
                        old_text,
                        new_text,
                    ),
                )
            )

        return IncrementalResult(
            changes=changes
        )

    @staticmethod
    def _normalize(text: str) -> str:
        """
        Normalize whitespace for comparison.
        """
        return " ".join(text.split())

    def compare_units(
        self,
        old_units: list[ContentUnit],
        new_units: list[ContentUnit],
    ) -> ContentIncrementalResult:
        """
        Compare generalized localizable content.

        SequenceMatcher compares the complete document
        sequence using:

            (element kind, normalized text)

        A new/changed unit is marked changed.

        Unchanged content after an insertion is NOT marked
        changed merely because its positional index shifted.
        """

        old_sequence = [
            (
                unit.kind,
                self._normalize(unit.text),
            )
            for unit in old_units
        ]

        new_sequence = [
            (
                unit.kind,
                self._normalize(unit.text),
            )
            for unit in new_units
        ]

        matcher = SequenceMatcher(
            a=old_sequence,
            b=new_sequence,
            autojunk=False,
        )

        changed_new_positions: set[int] = set()

        for (
            tag,
            old_start,
            old_end,
            new_start,
            new_end,
        ) in matcher.get_opcodes():

            if tag == "equal":
                continue

            if tag in ("replace", "insert"):
                changed_new_positions.update(
                    range(
                        new_start,
                        new_end,
                    )
                )

            # "delete" has no new content to localize.

        changes: list[ContentChange] = []

        for document_position, unit in enumerate(
            new_units
        ):
            old_text = None

            # This is only informational metadata.
            # The actual changed decision comes from
            # SequenceMatcher.
            for old_unit in old_units:
                if (
                    old_unit.kind == unit.kind
                    and self._normalize(
                        old_unit.text
                    )
                    == self._normalize(
                        unit.text
                    )
                ):
                    old_text = old_unit.text
                    break

            changes.append(
                ContentChange(
                    key=unit.key,
                    kind=unit.kind,
                    # IMPORTANT:
                    # preserve the unit's type-local index.
                    index=unit.index,
                    old_text=old_text,
                    new_text=unit.text,
                    changed=(
                        document_position
                        in changed_new_positions
                    ),
                )
            )

        return ContentIncrementalResult(
            changes=changes
        )