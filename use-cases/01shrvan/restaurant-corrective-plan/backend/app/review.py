from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .models import CorrectiveItem


Decision = Literal["pending", "approved", "rejected"]


class ReviewItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    item: CorrectiveItem
    decision: Decision = "pending"


def apply_decision(
    items: tuple[ReviewItem, ...],
    *,
    code: str,
    decision: Decision,
) -> tuple[ReviewItem, ...]:
    return tuple(
        ReviewItem(item=review.item, decision=decision)
        if review.item.code == code
        else review
        for review in items
    )


def undecided_codes(items: tuple[ReviewItem, ...]) -> tuple[str, ...]:
    return tuple(review.item.code for review in items if review.decision == "pending")

