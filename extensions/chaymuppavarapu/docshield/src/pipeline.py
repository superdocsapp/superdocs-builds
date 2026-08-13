from __future__ import annotations

from dataclasses import dataclass

from .document import Document
from .fingerprint import DocumentFingerprint, fingerprint
from .superdocs_client import SuperDocsClient, SuperDocsResponse
from .validator import ValidationResult, validate_document


@dataclass(frozen=True)
class PipelineResult:
    """
    Complete result of a DocShield-protected SuperDocs edit.

    `accepted` is True only when the edited document preserves all
    structural invariants checked by DocShield.
    """

    accepted: bool
    original: Document
    edited: Document | None
    original_fingerprint: DocumentFingerprint
    edited_fingerprint: DocumentFingerprint | None
    validation: ValidationResult | None
    response: SuperDocsResponse | None
    error: str | None = None


class DocShieldPipeline:
    """
    Protect a document while allowing SuperDocs to edit its content.

    Flow:

        original document
            ↓
        fingerprint
            ↓
        SuperDocs edit
            ↓
        parse returned HTML
            ↓
        fingerprint edited document
            ↓
        validate structural invariants
            ↓
        accept / reject
    """

    def __init__(
        self,
        client: SuperDocsClient,
    ) -> None:
        self.client = client

    def edit(
        self,
        document: Document,
        instruction: str,
    ) -> PipelineResult:
        """
        Send a document to SuperDocs and validate the returned document.

        Content changes are allowed.

        Structural changes such as element removal, element type changes,
        attribute changes, heading-level changes, and table-structure
        changes are rejected by the validator.
        """

        original_fingerprint = fingerprint(document)

        if document.source_format != "html":
            return PipelineResult(
                accepted=False,
                original=document,
                edited=None,
                original_fingerprint=original_fingerprint,
                edited_fingerprint=None,
                validation=None,
                response=None,
                error=(
                    "The SuperDocs pipeline currently accepts HTML "
                    "documents only."
                ),
            )

        try:
            if not document.raw_content:
                return PipelineResult(
                    accepted=False,
                    original=document,
                    edited=None,
                    original_fingerprint=original_fingerprint,
                    edited_fingerprint=None,
                    validation=None,
                    response=None,
                    error="Original document source is unavailable.",
                )

            html = self._serialize_document(document)

            response = self.client.edit(
                html=html,
                instruction=instruction,
            )

            edited = Document.from_html(response.html)
            edited_fingerprint = fingerprint(edited)

            validation = validate_document(
                before=document,
                after=edited,
            )

            return PipelineResult(
                accepted=validation.accepted,
                original=document,
                edited=edited if validation.accepted else None,
                original_fingerprint=original_fingerprint,
                edited_fingerprint=edited_fingerprint,
                validation=validation,
                response=response,
                error=(
                    None
                    if validation.accepted
                    else self._format_validation_error(validation)
                ),
            )

        except Exception as exc:
            return PipelineResult(
                accepted=False,
                original=document,
                edited=None,
                original_fingerprint=original_fingerprint,
                edited_fingerprint=None,
                validation=None,
                response=None,
                error=str(exc),
            )

    @staticmethod
    def _serialize_document(document: Document) -> str:
        """
        Return the original document source exactly as supplied.

        DocShield must send the original HTML to SuperDocs rather than
        reconstructing it from normalized elements. Reconstructing HTML
        would risk losing CSS, classes, inline styles, links, images,
        tables, and other formatting information.
        """

        if document.source_format != "html":
            raise ValueError(
                f"Cannot serialize unsupported format: "
                f"{document.source_format}"
            )

        if not document.raw_content:
            raise ValueError(
                "Original document source is unavailable."
            )

        return document.raw_content

    @staticmethod
    def _format_validation_error(
        validation: ValidationResult,
    ) -> str:
        """
        Turn validation failures into a useful human-readable message.
        """

        if validation.accepted:
            return ""

        lines = [
            "DocShield rejected the SuperDocs edit.",
            f"{validation.issue_count} invariant violation(s) detected:",
        ]

        for issue in validation.issues:
            location = (
                f" at position {issue.position}"
                if issue.position is not None
                else ""
            )

            lines.append(
                f"- [{issue.category}]{location}: "
                f"{issue.message}"
            )

        return "\n".join(lines)


def run_pipeline(
    document: Document,
    instruction: str,
    client: SuperDocsClient,
) -> PipelineResult:
    """
    Convenience function for callers that do not need to instantiate
    DocShieldPipeline directly.
    """

    return DocShieldPipeline(client).edit(
        document=document,
        instruction=instruction,
    )