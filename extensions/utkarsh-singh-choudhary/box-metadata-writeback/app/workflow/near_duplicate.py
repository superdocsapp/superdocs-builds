"""Near-duplicate detection across distinct files.

Idempotency (app/workflow/idempotency.py) already handles the exact
case: same file_id, same content sha1, don't reprocess. It has nothing
to say about a DIFFERENT file_id whose content is 99% identical to one
already processed -- e.g. the same contract re-uploaded under a new
Box file ID, a trivial timestamp-only edit, or a duplicate submission.
Each of those currently gets a full companion document generated and
its own independent metadata write, silently duplicating work and
creating two "originals" in the retention system.

This module computes a similarity fingerprint (shingled Jaccard
similarity over whitespace-normalized word tokens -- deliberately not
a cryptographic hash, since the whole point is tolerance to small
edits) for every processed file's source content, and can check a new
document against everything already fingerprinted for the tenant.

Flags, never blocks: a near-duplicate is reported on the RunReport as
information for a human (or a downstream dedup workflow) to act on.
Auto-skipping a near-duplicate would be exactly the kind of "guess
instead of leaving it to a human" behavior the governance section of
the brief argues against -- two contracts can legitimately be 95%
similar (a template with one clause changed) and still both need their
own retention record.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Optional

SHINGLE_SIZE = 3  # 3-word shingles -- fine-grained enough that a single-token edit (e.g. one date) doesn't wipe out similarity on short documents, while still distinctive enough to avoid false positives between unrelated short documents
DEFAULT_SIMILARITY_THRESHOLD = 0.85


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _shingles(text: str, size: int = SHINGLE_SIZE) -> set[str]:
    tokens = _tokenize(text)
    if len(tokens) < size:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)}


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """1.0 for identical (post-tokenization) text, 0.0 for no shared
    5-word shingles at all. Symmetric, so argument order doesn't
    matter -- useful since callers compare a new document against
    every previously-seen one without needing to track which was
    "first"."""
    shingles_a, shingles_b = _shingles(text_a), _shingles(text_b)
    if not shingles_a and not shingles_b:
        return 1.0  # both empty -- trivially identical
    if not shingles_a or not shingles_b:
        return 0.0
    intersection = len(shingles_a & shingles_b)
    union = len(shingles_a | shingles_b)
    return intersection / union if union else 0.0


@dataclass
class NearDuplicateMatch:
    file_id: str
    similarity: float


class NearDuplicateDetector:
    """One instance per tenant. Stores every processed file's shingle
    set (not the raw text) to keep memory bounded and avoid re-tokenizing
    on every comparison. Thread-safe: check_and_register is called from
    the same code path as everything else in a concurrent batch run."""

    def __init__(self, similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD) -> None:
        self.similarity_threshold = similarity_threshold
        self._lock = threading.Lock()
        self._fingerprints: dict[str, set[str]] = {}  # file_id -> shingle set

    def check_and_register(self, file_id: str, content_text: str) -> Optional[NearDuplicateMatch]:
        """Compares `content_text` against every OTHER file_id already
        registered for this tenant, returns the best match at or above
        similarity_threshold (or None), and registers this file's
        fingerprint for future comparisons regardless of outcome --
        every processed file becomes a candidate match for the next
        one, whether or not it was itself flagged.

        Re-registering the same file_id (e.g. a version bump) simply
        overwrites its fingerprint -- comparisons always use the latest
        content for that file_id, matching how idempotency already
        treats a version bump as a fresh thing to process."""
        new_shingles = _shingles(content_text)
        best: Optional[NearDuplicateMatch] = None
        with self._lock:
            for other_id, other_shingles in self._fingerprints.items():
                if other_id == file_id:
                    continue
                if not new_shingles and not other_shingles:
                    similarity = 1.0
                elif not new_shingles or not other_shingles:
                    similarity = 0.0
                else:
                    intersection = len(new_shingles & other_shingles)
                    union = len(new_shingles | other_shingles)
                    similarity = intersection / union if union else 0.0
                if similarity >= self.similarity_threshold and (best is None or similarity > best.similarity):
                    best = NearDuplicateMatch(file_id=other_id, similarity=similarity)
            self._fingerprints[file_id] = new_shingles
        return best
