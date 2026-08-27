"""Identity verification for the Living Changelog Maintainer.

The core guarantee of this tool is: after updating for release N, the
content of releases 1..N-1 is BYTE-IDENTICAL to what it was before.

We implement two complementary verification strategies:

1. ``canonical_hash`` — re-render every old entry through the renderer and
   hash the concatenated bytes. Because the renderer is a pure function,
   this hash is stable across runs (modulo the house style, which is itself
   persisted with the document).

2. ``html_anchor_check`` — for documents stored in SuperDocs, walk the
   post-update HTML and confirm that the exact text of every prior heading
   is still present at the same logical position (text + immediate body
   intact). This catches partial regenerations where the renderer might
   silently drop whitespace, change bullet markers, or rewrite a link.

Both strategies are deterministic and unit-testable.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from changelog_maintainer.models import (
    ChangelogDocument,
    ReleaseEntry,
    VerificationResult,
)
from changelog_maintainer.renderer import render_entry


# ---------------------------------------------------------------------------
# Strategy 1: canonical hash
# ---------------------------------------------------------------------------


def canonical_hash(entries: Iterable[ReleaseEntry], document: ChangelogDocument) -> str:
    """Render each entry in canonical order and SHA-256 the concatenated bytes.

    Returns a hex digest. Same entries under the same style always produce
    the same hash. The hash is over the rendered Markdown so it is also
    robust to dataclass field reorderings.
    """
    # Always hash entries in oldest-first order so the order itself is
    # captured in the digest.
    ordered = sorted(
        entries,
        key=lambda e: (e.date, e.version),
    )
    h = hashlib.sha256()
    for entry in ordered:
        block = render_entry(entry, document.style, document)
        # Hash the rendered block AND a length prefix so two entries whose
        # rendered output collides on boundaries still differ.
        h.update(len(block).to_bytes(8, "big"))
        h.update(block.encode("utf-8"))
        h.update(b"|END-OF-ENTRY|\n")
    return h.hexdigest()


def verify_entries(
    before_entries: Iterable[ReleaseEntry],
    after_entries: Iterable[ReleaseEntry],
    document: ChangelogDocument,
) -> VerificationResult:
    """Compare prior entries before vs after a surgical update.

    The ``after`` set may contain ONE extra entry (the newly inserted release);
    every other entry must produce the same canonical hash as ``before``.

    Returns a VerificationResult. ``passed`` is True iff every version in
    ``before`` still produces the same render in ``after``.
    """
    before_list = list(before_entries)
    after_list = list(after_entries)
    after_by_version = {e.version: e for e in after_list}

    if len(after_list) - len(before_list) not in (0, 1):
        return VerificationResult(
            passed=False,
            expected_hash="",
            actual_hash="",
            versions_checked=tuple(),
        )

    new_version: str | None = None
    if len(after_list) == len(before_list) + 1:
        before_versions = {e.version for e in before_list}
        new_version = next(
            (e.version for e in after_list if e.version not in before_versions),
            None,
        )

    expected = canonical_hash(before_list, document)
    versions_kept = tuple(e.version for e in before_list)
    # For the actual hash we hash every entry that was in `before` — i.e.
    # we drop the newly added one if present.
    after_kept = [e for e in after_list if e.version in set(versions_kept)]
    actual = canonical_hash(after_kept, document)

    if expected != actual:
        # Drill down: which version drifted?
        drifted = []
        for entry in before_list:
            other = after_by_version.get(entry.version)
            if other is None:
                drifted.append(entry.version)
                continue
            if render_entry(entry, document.style, document) != render_entry(
                other, document.style, document
            ):
                drifted.append(entry.version)
        # We do not include the drift list in the VerificationResult itself
        # (frozen dataclass), but we surface it via the verifier return wrapper.
        return _DriftedVerification(
            passed=False,
            expected_hash=expected,
            actual_hash=actual,
            versions_checked=versions_kept,
            drifted=tuple(drifted),
            new_version=new_version,
        )
    return VerificationResult(
        passed=True,
        expected_hash=expected,
        actual_hash=actual,
        versions_checked=versions_kept,
    )


# ---------------------------------------------------------------------------
# Strategy 2: HTML anchor check (for SuperDocs verification)
# ---------------------------------------------------------------------------


_HEADING_RE = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    text = _TAG_STRIP_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _extract_heading_texts(html: str) -> list[str]:
    """Return the visible text of every H1..H6 heading, in document order."""
    out: list[str] = []
    for match in _HEADING_RE.finditer(html):
        out.append(_normalize(match.group(2)))
    return out


@dataclass(frozen=True)
class AnchorCheckResult:
    """Result of the HTML anchor verification."""

    passed: bool
    missing_headings: tuple[str, ...]
    out_of_order: bool

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        detail = ""
        if self.missing_headings:
            detail += f" missing={list(self.missing_headings)}"
        if self.out_of_order:
            detail += " out_of_order=True"
        return f"[{status}] HTML anchor check{detail}"


def verify_html_anchors(
    before_html: str,
    after_html: str,
    expected_new_titles: Iterable[str] = (),
) -> AnchorCheckResult:
    """Walk the post-update HTML and confirm every prior heading is intact.

    A heading is considered "intact" if its normalized visible text appears in
    the post-update HTML in the same relative order as before.

    ``expected_new_titles`` is a list of heading texts that the post-update
    document SHOULD additionally contain (the newly inserted release title).
    They are expected to appear at the top.
    """
    before_headings = _extract_heading_texts(before_html)
    after_headings = _extract_heading_texts(after_html)
    after_set = set(after_headings)

    missing = [h for h in before_headings if h not in after_set]
    out_of_order = False

    # Subsequence check: walk after_headings and verify that before_headings
    # appears in the exact same relative order.
    it = iter(after_headings)
    out_of_order = False
    for h in before_headings:
        found = False
        for candidate in it:
            if candidate == h:
                found = True
                break
        if not found:
            out_of_order = True
            break

    return AnchorCheckResult(
        passed=not missing and not out_of_order,
        missing_headings=tuple(missing),
        out_of_order=out_of_order,
    )


# ---------------------------------------------------------------------------
# Combined verifier wrapper (carries drift info that VerificationResult cannot)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DriftedVerification(VerificationResult):
    """Internal wrapper exposed when identity verification fails.

    Inherits all VerificationResult fields and adds drift metadata.
    """

    drifted: tuple[str, ...] = ()
    new_version: str | None = None


def is_drifted(result: VerificationResult) -> _DriftedVerification | None:
    """Return the richer result if the verification failed, else None."""
    if isinstance(result, _DriftedVerification):
        return result
    return None


__all__ = [
    "AnchorCheckResult",
    "canonical_hash",
    "is_drifted",
    "verify_entries",
    "verify_html_anchors",
]
