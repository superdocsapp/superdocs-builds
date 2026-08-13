from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .document import Document
from .fingerprint import DocumentFingerprint, fingerprint


@dataclass(frozen=True)
class ValidationIssue:
    """A structural or formatting invariant violation."""

    category: str
    message: str
    position: int | None = None
    before: Any = None
    after: Any = None


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating an edited document."""

    accepted: bool
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)
    before: DocumentFingerprint | None = None
    after: DocumentFingerprint | None = None

    @property
    def issue_count(self) -> int:
        return len(self.issues)


class DocumentValidator:
    """
    Validate that an edited document preserves structural invariants.

    Text content is intentionally NOT treated as an invariant because
    SuperDocs is expected to edit document content.

    The following are protected by default:

    - element count
    - element type
    - element ordering
    - element-local index
    - HTML attributes
    - structural formatting metadata
    - table row/column structure
    - image source/alt presence
    - heading levels
    """

    def validate(
        self,
        before: Document,
        after: Document,
    ) -> ValidationResult:
        before_fp = fingerprint(before)
        after_fp = fingerprint(after)

        issues: list[ValidationIssue] = []

        if before.source_format != after.source_format:
            issues.append(
                ValidationIssue(
                    category="source_format",
                    message=(
                        "Document source format changed."
                    ),
                    before=before.source_format,
                    after=after.source_format,
                )
            )

        before_elements = before.elements
        after_elements = after.elements

        if len(before_elements) != len(after_elements):
            issues.append(
                ValidationIssue(
                    category="element_count",
                    message=(
                        "The number of document elements changed."
                    ),
                    before=len(before_elements),
                    after=len(after_elements),
                )
            )

        maximum = max(
            len(before_elements),
            len(after_elements),
        )

        for position in range(maximum):
            old = (
                before_elements[position]
                if position < len(before_elements)
                else None
            )

            new = (
                after_elements[position]
                if position < len(after_elements)
                else None
            )

            if old is None:
                issues.append(
                    ValidationIssue(
                        category="element_added",
                        message=(
                            "An element was added to the document."
                        ),
                        position=position,
                        after={
                            "type": new.element_type,
                            "index": new.index,
                        },
                    )
                )
                continue

            if new is None:
                issues.append(
                    ValidationIssue(
                        category="element_removed",
                        message=(
                            "An element was removed from the document."
                        ),
                        position=position,
                        before={
                            "type": old.element_type,
                            "index": old.index,
                        },
                    )
                )
                continue

            if old.element_type != new.element_type:
                issues.append(
                    ValidationIssue(
                        category="element_type",
                        message=(
                            "An element changed type."
                        ),
                        position=position,
                        before=old.element_type,
                        after=new.element_type,
                    )
                )
                continue

            if old.index != new.index:
                issues.append(
                    ValidationIssue(
                        category="element_index",
                        message=(
                            "An element's occurrence index changed."
                        ),
                        position=position,
                        before=old.index,
                        after=new.index,
                    )
                )

            if old.attributes != new.attributes:
                issues.append(
                    ValidationIssue(
                        category="attributes",
                        message=(
                            "Element attributes changed."
                        ),
                        position=position,
                        before=old.attributes,
                        after=new.attributes,
                    )
                )

            if old.formatting != new.formatting:
                issues.append(
                    ValidationIssue(
                        category="formatting",
                        message=(
                            "Structural formatting metadata changed."
                        ),
                        position=position,
                        before=old.formatting,
                        after=new.formatting,
                    )
                )

        return ValidationResult(
            accepted=not issues,
            issues=tuple(issues),
            before=before_fp,
            after=after_fp,
        )


def validate_document(
    before: Document,
    after: Document,
) -> ValidationResult:
    """
    Convenience wrapper around DocumentValidator.
    """
    return DocumentValidator().validate(
        before,
        after,
    )
