from __future__ import annotations

from dataclasses import dataclass

from .source import SourceDocument


@dataclass(frozen=True)
class SourceValidationResult:
    """
    Result of comparing an edited source against the original source.

    Source identity is deliberately separate from document content
    validation. Two documents may legitimately have different content
    while still preserving the protected source structure.
    """

    identical: bool
    original_sha256: str
    edited_sha256: str

    @property
    def changed(self) -> bool:
        return not self.identical


def validate_source(
    original: SourceDocument,
    edited_bytes: bytes,
) -> SourceValidationResult:
    """
    Compare edited bytes against the original source.

    This does NOT reject every edit. It only answers whether the raw
    package/source bytes are identical.
    """

    import hashlib

    edited_sha256 = hashlib.sha256(
        edited_bytes
    ).hexdigest()

    return SourceValidationResult(
        identical=(
            original.sha256 == edited_sha256
        ),
        original_sha256=original.sha256,
        edited_sha256=edited_sha256,
    )
