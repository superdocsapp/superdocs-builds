from __future__ import annotations

import re
from collections.abc import Iterable

AUDIENCE_SHARED = "shared"
AUDIENCE_INTERNAL = "internal"

SIDES = ("vendor", "customer")

_MIN_MEANINGFUL_LENGTH = 12


class BoundaryViolation(Exception):
    def __init__(self, reason: str, context: str):
        self.reason = reason
        self.context = context
        super().__init__(f"boundary violation ({context}): {reason}")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def classify_source(channel_id: str, shared_channel_id: str) -> str:
    return AUDIENCE_SHARED if channel_id == shared_channel_id else AUDIENCE_INTERNAL


def assert_instruction_is_shareable(instruction: str, source_audience: str, context: str) -> None:
    if source_audience != AUDIENCE_SHARED:
        raise BoundaryViolation(
            "edit instructions may only originate from the shared channel;"
            " internal commentary must never drive the shared document",
            context,
        )
    if not _normalize(instruction):
        raise BoundaryViolation("instruction is empty", context)


def assert_internal_note_stays_internal(
    note_body: str, destination_audience: str, context: str
) -> None:
    if destination_audience != AUDIENCE_INTERNAL:
        raise BoundaryViolation(
            "an internal note was routed to a non-internal destination",
            context,
        )


def assert_shared_payload_is_clean(
    payload_text: str,
    internal_materials: Iterable[str],
    context: str,
) -> None:
    normalized_payload = _normalize(payload_text)
    for material in internal_materials:
        candidate = _normalize(material)
        if len(candidate) < _MIN_MEANINGFUL_LENGTH:
            continue
        if candidate in normalized_payload:
            raise BoundaryViolation(
                f"outbound shared payload contains internal material: {candidate[:60]!r}...",
                context,
            )


def collect_internal_material(notes_bodies: Iterable[str]) -> list[str]:
    return [body for body in notes_bodies if body and body.strip()]
