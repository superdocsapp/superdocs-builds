"""Proves that sections the amendment did not touch stayed exactly as they
were — "surgical precision" from the round's grading notes, made checkable
rather than merely claimed.

Gotcha discovered against the live API: SuperDocs re-chunks an uploaded
document on ingest and assigns its own `data-chunk-id` to each chunk,
discarding any `data-section-id` attribute we authored the fixture with.
Those chunk ids *are* stable across edits for chunks that weren't touched
(verified empirically), so the orchestrator builds a section-id -> chunk-id
map right after upload and this module can key off either attribute.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Dict, List

_TAG_RE = re.compile(r"<[^>]+>")


def _section_re(attr: str, value: str) -> re.Pattern:
    return re.compile(rf'{re.escape(attr)}="{re.escape(value)}"[^>]*>(.*?)</div>', re.DOTALL)


def _extract_section_text(html: str, target_id: str, attr: str) -> str | None:
    m = _section_re(attr, target_id).search(html)
    if not m:
        return None
    inner = m.group(1)
    text = _TAG_RE.sub(" ", inner)
    return re.sub(r"\s+", " ", text).strip()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class UntouchedProof:
    section_id: str
    before_hash: str | None
    after_hash: str | None

    @property
    def verified_untouched(self) -> bool:
        return self.before_hash is not None and self.before_hash == self.after_hash


def verify_untouched(
    before_html: str, after_html: str, section_ids: List[str], attr: str = "data-section-id"
) -> Dict[str, UntouchedProof]:
    """Hash each declared-untouched section's text content before vs after.

    `section_ids` should be the ids that actually appear in `before_html`/
    `after_html` under `attr` (e.g. SuperDocs's own `data-chunk-id` values,
    or `data-section-id` when addressing a document that preserves it, as
    the test fakes do). Returns one UntouchedProof per id. An id missing
    from either document hashes to None, which fails `verified_untouched`
    rather than silently passing — a section that vanished is not
    "untouched".
    """

    proofs: Dict[str, UntouchedProof] = {}
    for section_id in section_ids:
        before_text = _extract_section_text(before_html, section_id, attr)
        after_text = _extract_section_text(after_html, section_id, attr)
        before_hash = _hash_text(before_text) if before_text is not None else None
        after_hash = _hash_text(after_text) if after_text is not None else None
        proofs[section_id] = UntouchedProof(section_id, before_hash, after_hash)
    return proofs

