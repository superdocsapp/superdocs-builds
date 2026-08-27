"""Proof that nothing else moved.

The product's central claim is that applying a correction changes the
claim and nothing around it. That claim is worth exactly as much as the
evidence for it, so this module produces evidence rather than assurances:
a per-chunk SHA-256 table, before and after, with the changed chunks named.

One trap, learned on the wire: **exports strip `data-chunk-id`.** Comparing
exported files would therefore compare a different surface from the one
that was edited, and would silently miss chunk-level damage. Always compare
*stored session HTML*.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_CHUNK_RE = re.compile(
    r'<(?P<tag>[a-zA-Z][\w-]*)\b[^>]*\bdata-chunk-id="(?P<cid>[^"]+)"[^>]*>'
    r"(?P<body>.*?)</(?P=tag)>",
    re.DOTALL,
)


def chunk_hashes(html: str) -> dict[str, str]:
    """SHA-256 per chunk, keyed by `data-chunk-id`.

    Hashes the whole element including its tag and attributes, so a change
    to formatting or an attribute counts as a change — which is the point.
    """
    out: dict[str, str] = {}
    for m in _CHUNK_RE.finditer(html):
        out[m.group("cid")] = hashlib.sha256(
            m.group(0).encode("utf-8")
        ).hexdigest()
    return out


@dataclass(frozen=True)
class SurgicalProof:
    """The evidence artifact for one applied batch."""

    changed: tuple[str, ...]      # chunk ids whose bytes differ
    unchanged: tuple[str, ...]    # chunk ids byte-identical before and after
    added: tuple[str, ...]        # chunk ids present only after
    removed: tuple[str, ...]      # chunk ids present only before
    intended: tuple[str, ...]     # chunk ids the batch meant to touch

    @property
    def collateral(self) -> tuple[str, ...]:
        """Chunks that changed WITHOUT being targeted. Must always be empty."""
        return tuple(c for c in self.changed if c not in self.intended)

    @property
    def ok(self) -> bool:
        """True only if nothing beyond the intended chunks moved."""
        return not self.collateral and not self.added and not self.removed

    def render(self) -> str:
        lines = [
            "surgical precision proof",
            f"  intended  : {len(self.intended)} chunk(s) {list(self.intended)}",
            f"  changed   : {len(self.changed)} chunk(s) {list(self.changed)}",
            f"  unchanged : {len(self.unchanged)} chunk(s) byte-identical",
        ]
        if self.added:
            lines.append(f"  ADDED     : {list(self.added)}")
        if self.removed:
            lines.append(f"  REMOVED   : {list(self.removed)}")
        if self.collateral:
            lines.append(f"  [X] COLLATERAL DAMAGE: {list(self.collateral)}")
            lines.append("  VERDICT   : FAILED — untargeted content was modified")
        else:
            lines.append("  VERDICT   : PASSED — only intended chunks changed")
        return "\n".join(lines)


def prove_surgical(before_html: str, after_html: str,
                   intended_chunk_ids: list[str]) -> SurgicalProof:
    """Compare stored HTML before and after, per chunk.

    Pass the *stored session HTML* on both sides, never an export.
    """
    before, after = chunk_hashes(before_html), chunk_hashes(after_html)
    common = [c for c in before if c in after]
    return SurgicalProof(
        changed=tuple(c for c in common if before[c] != after[c]),
        unchanged=tuple(c for c in common if before[c] == after[c]),
        added=tuple(c for c in after if c not in before),
        removed=tuple(c for c in before if c not in after),
        intended=tuple(intended_chunk_ids),
    )
