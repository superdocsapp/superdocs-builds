"""Source immutability.

The source document is the one artifact this system is never allowed to
change. Every pipeline stage that has read access to the source text must be
able to prove, on demand, that the bytes it is holding are exactly the bytes
that were loaded at the start of the run.

Design:

- ``SourceGuard.snapshot`` is called exactly once, immediately after the raw
  source bytes are read from disk, before any parsing happens.
- ``SourceGuard.verify`` is called at every pipeline checkpoint that touches
  the source (after parsing, after each section is processed, after report
  generation). It re-hashes whatever text it is handed and compares against
  the frozen snapshot.
- Verification never repairs or mutates anything. A mismatch raises
  ``SourceIntegrityError`` — the pipeline stops rather than continuing on an
  unverified source.

This module has no dependency on the LLM providers or any other pipeline
stage. It is deliberately the simplest, most heavily tested piece of the
system, because it is the one property the whole project exists to protect.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from drift_check.models import Section, VerificationResult, utc_now_iso


class SourceIntegrityError(RuntimeError):
    """Raised when the source document is found to have changed after snapshotting."""


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    document_id: str
    whole_document_hash: str
    section_hashes: tuple[tuple[str, str], ...]  # (section_id, content_hash), stable order
    section_count: int
    char_count: int

    def section_hash_map(self) -> dict[str, str]:
        return dict(self.section_hashes)


class SourceGuard:
    """Holds an immutable snapshot of a source document and verifies against it."""

    def __init__(self, snapshot: SourceSnapshot) -> None:
        self._snapshot = snapshot

    @classmethod
    def from_raw_text(cls, document_id: str, raw_text: str, sections: tuple[Section, ...]) -> SourceGuard:
        snapshot = SourceSnapshot(
            document_id=document_id,
            whole_document_hash=sha256_hex(raw_text),
            section_hashes=tuple((s.id, s.content_hash) for s in sections),
            section_count=len(sections),
            char_count=len(raw_text),
        )
        return cls(snapshot)

    @property
    def snapshot(self) -> SourceSnapshot:
        return self._snapshot

    def verify_whole_document(self, current_raw_text: str) -> VerificationResult:
        actual = sha256_hex(current_raw_text)
        expected = self._snapshot.whole_document_hash
        ok = actual == expected
        return VerificationResult(
            ok=ok,
            checked_at=utc_now_iso(),
            expected_hash=expected,
            actual_hash=actual,
            message="source unchanged" if ok else "SOURCE MUTATION DETECTED: whole-document hash mismatch",
        )

    def verify_sections(self, current_sections: tuple[Section, ...]) -> VerificationResult:
        expected_map = self._snapshot.section_hash_map()
        current_map = {s.id: s.content_hash for s in current_sections}
        ok = expected_map == current_map
        # A single combined hash of the sorted mapping gives a stable single
        # "actual"/"expected" hash pair to report, while the equality check
        # above is what actually decides pass/fail (so key additions/removals
        # are caught, not just value changes).
        expected_combined = sha256_hex(repr(sorted(expected_map.items())))
        actual_combined = sha256_hex(repr(sorted(current_map.items())))
        message = "all section hashes match" if ok else "SOURCE MUTATION DETECTED: section hash mismatch"
        return VerificationResult(
            ok=ok,
            checked_at=utc_now_iso(),
            expected_hash=expected_combined,
            actual_hash=actual_combined,
            message=message,
        )

    def assert_intact(self, current_raw_text: str, current_sections: tuple[Section, ...]) -> VerificationResult:
        """Verify both whole-document and per-section hashes; raise on any mismatch."""
        whole = self.verify_whole_document(current_raw_text)
        if not whole.ok:
            raise SourceIntegrityError(whole.message)
        sections = self.verify_sections(current_sections)
        if not sections.ok:
            raise SourceIntegrityError(sections.message)
        return whole
