"""Holds low-confidence extracted fields out of Box metadata until a
human approves or rejects them.

This is the Task-2-scale version of the same idea the brief's Task 1
section spends a whole paragraph on ("A human gates all of it"): here,
instead of gating conflicts between documents, we gate individual
extracted-field confidence. A field below `threshold` never reaches
Box's metadata template on its own -- it sits in this queue until a
person calls approve() or reject().
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Optional

from app.models import PendingReview

DEFAULT_CONFIDENCE_THRESHOLD = 0.7


class ReviewQueue:
    """
    threshold: the global default gate.
    field_thresholds: optional per-field override, e.g.
        {"contract_value": 0.85, "counterparty_name": 0.6}
    A field not listed falls back to `threshold`. This lets a tenant
    set a tighter bar on fields where being wrong is expensive
    (money, legal terms) and a looser one where it isn't -- previously
    a single global constant, per the round-2 writeup's own "not yet
    built" list.
    """

    def __init__(
        self,
        threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        field_thresholds: Optional[dict[str, float]] = None,
    ) -> None:
        self.threshold = threshold
        self.field_thresholds = dict(field_thresholds or {})
        self._lock = threading.Lock()
        self._reviews: dict[str, PendingReview] = {}

    def threshold_for(self, field_name: str) -> float:
        return self.field_thresholds.get(field_name, self.threshold)

    def requires_review(self, field_name: str, confidence: float) -> bool:
        return confidence < self.threshold_for(field_name)

    def stage(
        self,
        file_id: str,
        version_sha1: str,
        field_name: str,
        value: str,
        confidence: float,
        source_session_id: Optional[str] = None,
    ) -> PendingReview:
        review = PendingReview(
            review_id=f"rev-{uuid.uuid4().hex[:8]}",
            file_id=file_id,
            version_sha1=version_sha1,
            field_name=field_name,
            proposed_value=value,
            confidence=confidence,
            created_at=time.time(),
            source_session_id=source_session_id,
        )
        with self._lock:
            self._reviews[review.review_id] = review
        return review

    def list_pending(self, file_id: Optional[str] = None) -> list[PendingReview]:
        with self._lock:
            items = [r for r in self._reviews.values() if r.status == "pending"]
        if file_id:
            items = [r for r in items if r.file_id == file_id]
        return sorted(items, key=lambda r: r.created_at)

    def get(self, review_id: str) -> Optional[PendingReview]:
        with self._lock:
            return self._reviews.get(review_id)

    def decide(self, review_id: str, approve: bool) -> PendingReview:
        with self._lock:
            review = self._reviews.get(review_id)
            if review is None:
                raise KeyError(review_id)
            if review.status != "pending":
                raise ValueError(f"review {review_id} already {review.status}")
            review.status = "approved" if approve else "rejected"
            review.decided_at = time.time()
            return review
